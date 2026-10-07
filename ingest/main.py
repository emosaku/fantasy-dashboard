"""League Lab's ingest job: refreshes many leagues per run, gently.

One Cloud Run Job with parallel tasks. Each task takes its slice of the leagues to
refresh (CLOUD_RUN_TASK_INDEX of CLOUD_RUN_TASK_COUNT): active leagues someone has
opened in the last 14 days, or exactly LEAGUE_IDS for a manual refresh. Per league,
with a random pause between leagues and backoff on every ESPN call, it fetches only
what changed -- the still-open matchup weeks, activity newer than it already has,
games-played history for players it hasn't seen -- and replaces that league's rows.
Then one refresh of the precomputed m_* tables covers all of the task's leagues.

A league is loaded in its locked format (categories or points; see catalog.py):
the format is confirmed at sign-up and fixed for the season. If ESPN's scoring type
stops matching it, the league is flagged (format_mismatch) and not refreshed until
the site owner reloads it in the right format (scripts/set_format.py). A points
league also loads its point values, every player's fantasy points, the season's
weekly scores and the NBA schedule. Every league loads what the Draft Tool reads: the
draft's settings, the 400 best players by ESPN's draft rank for its format (ADP,
ranks, projections, games-played history) and ESPN's picks once it shares them.

A league that fails (made private, deleted, unsupported) is marked with the reason
in the registry; the others carry on. The run fails -- triggering the alert -- only
when every league it tried failed. Leagues marked "deleting" are purged: all their
rows, their registry entries and any stored credentials.

Env: GCP_PROJECT_ID, SEASON (required); BIGQUERY_DATASET (league_lab); LEAGUE_IDS
(comma list: manual refresh); PURGE_ONLY (1: only purge); FREE_AGENT_COUNT (100);
HISTORY_SEASONS (3); DRAFT_POOL (400).
"""

import datetime as dt
import os
import random
import sys
import time

from google.cloud import bigquery

from ingest import registry
from ingest.bigquery_load import in_list, league_scope, replace_rows
from ingest.catalog import (
    PLAYER_STATS,
    POINTS,
    league_categories,
    league_format,
    league_scoring,
    scoring_type,
)
from ingest.credentials import EXPIRED, NeedsLogin, cookies_for
from ingest.espn_client import (
    LeagueNotAccessible,
    build_league,
    fetch_activity,
    fetch_draft_pool,
    fetch_player_history,
    fetch_player_info,
    fetch_settings,
    fetch_views,
    polite,
)
from ingest.materialize import MATERIALIZED_VIEWS, refresh_statements, table_for
from ingest.transform import (
    bench_slots,
    draft_settings,
    lineup_slots,
    points_mismatches,
    transform_draft_picks,
    transform_draft_pool,
    transform_draft_pool_stats,
    transform_free_agents,
    transform_league_categories,
    transform_league_scoring,
    transform_league_settings,
    transform_matchup_categories,
    transform_matchup_scores,
    transform_player_details,
    transform_player_points,
    transform_player_seasons,
    transform_player_stats,
    transform_pro_schedule,
    transform_rosters,
    transform_teams,
    transform_transactions,
)

LEAGUE_TABLES = [
    "league_settings", "league_categories", "teams", "matchup_categories", "rosters",
    "free_agents", "player_stats", "transactions", "player_details", "league_scoring",
    "player_points", "matchup_scores", "pro_schedule", "draft_pool", "draft_pool_stats",
    "draft_picks",
]  # fmt: skip


class FormatMismatch(Exception):
    """ESPN's scoring type no longer matches the league's locked format."""

    def __init__(self, espn_format: str):
        super().__init__(f"ESPN now scores this league by {espn_format}.")
        self.espn_format = espn_format


STAGGER_SECONDS = (2.0, 8.0)


class Config:
    def __init__(self, env=os.environ):
        self.project = env["GCP_PROJECT_ID"]
        self.dataset = env.get("BIGQUERY_DATASET", "league_lab")
        self.location = env.get("BIGQUERY_LOCATION", "us-west1")
        self.season = int(env["SEASON"])
        self.free_agents = int(env.get("FREE_AGENT_COUNT", "100"))
        self.history_seasons = int(env.get("HISTORY_SEASONS", "3"))
        self.draft_pool = int(env.get("DRAFT_POOL", "400"))
        ids = env.get("LEAGUE_IDS", "").strip()
        self.only_ids = {int(i) for i in ids.split(",") if i.strip()} if ids else None
        self.purge_only = env.get("PURGE_ONLY") == "1"
        self.task_index = int(env.get("CLOUD_RUN_TASK_INDEX", "0"))
        self.task_count = int(env.get("CLOUD_RUN_TASK_COUNT", "1"))


def missing_history(client, cfg, player_ids) -> dict[int, list[int]]:
    """{past season: player ids with no player_seasons row yet}."""
    seasons = list(range(cfg.season - cfg.history_seasons, cfg.season))
    if not player_ids:
        return {}
    seen = client.query(
        f"SELECT player_id, history_season FROM `{cfg.project}.{cfg.dataset}.player_seasons` "
        f"WHERE {in_list('player_id', player_ids)} AND {in_list('history_season', seasons)}"
    ).result()
    have = {(row.player_id, row.history_season) for row in seen}
    return {s: [p for p in player_ids if (p, s) not in have] for s in seasons}


def history_average(client, cfg, player_ids) -> dict[int, float]:
    """Each player's average games played over the last HISTORY_SEASONS seasons he
    played (player_seasons)."""
    if not player_ids:
        return {}
    seasons = list(range(cfg.season - cfg.history_seasons, cfg.season))
    rows = client.query(
        f"SELECT player_id, AVG(games_played) AS games "
        f"FROM `{cfg.project}.{cfg.dataset}.player_seasons` "
        f"WHERE {in_list('player_id', player_ids)} AND {in_list('history_season', seasons)} "
        "AND games_played IS NOT NULL GROUP BY player_id"
    ).result()
    return {int(r.player_id): float(r.games) for r in rows}


def ingest_league(league_doc: dict, client, db, cfg: Config, now: dt.datetime) -> dict:
    """Refresh one league; returns the registry fields to record."""
    league_id = league_doc["league_id"]
    season = int(league_doc.get("season") or cfg.season)
    cookies = cookies_for(league_doc, cfg.project)

    try:
        raw = fetch_settings(league_id, season, cookies)
    except LeagueNotAccessible as error:
        # With a saved login, a refusal means the login expired, not a deleted league.
        if cookies and "no basketball league" not in str(error):
            raise NeedsLogin(EXPIRED) from None
        raise
    espn_format = league_format(raw["scoringSettings"])
    locked = league_doc.get("format")
    if locked and locked != espn_format:
        raise FormatMismatch(espn_format)
    points = (locked or espn_format) == POINTS
    categories = [] if points else league_categories(raw["scoringSettings"])
    scoring = league_scoring(raw["scoringSettings"]) if points else []
    league = build_league(league_id, season, cookies)
    current = league.currentMatchupPeriod
    # Weeks before the previous one are final; re-fetch only the last two.
    first = max(1, int(league_doc.get("scores_final_through") or 0) + 1)
    periods = list(range(first, current + 1))
    free_agents = polite(lambda: league.free_agents(size=cfg.free_agents))
    rostered = [p for team in league.teams for p in team.roster]
    pool_ids = sorted({p.playerId for p in rostered} | {p.playerId for p in free_agents})
    draft_detail = fetch_views(league_id, season, ["mDraftDetail"], cookies).get("draftDetail")
    draft_records = fetch_draft_pool(
        league_id, season, cookies, cfg.draft_pool, "STANDARD" if points else "ROTO"
    )
    draft_ids = [int(r["id"]) for r in draft_records]
    try:
        topics = fetch_activity(
            league_id, season, int(league_doc.get("activity_through_ms") or 0), cookies
        )
        activity_needs_login = False
    except LeagueNotAccessible:
        # Some public leagues share everything but their activity feed without a login.
        if cookies:
            raise NeedsLogin(EXPIRED) from None
        topics, activity_needs_login = [], True
    details = fetch_player_info(league_id, season, pool_ids, cookies)
    history = {
        s: (ids, fetch_player_history(s, ids) if ids else [])
        for s, ids in missing_history(client, cfg, sorted(set(pool_ids) | set(draft_ids))).items()
    }

    def load(table, df, extra=""):
        return replace_rows(
            client, cfg.project, cfg.dataset, table, df, league_scope(league_id, extra)
        )

    settings = transform_league_settings(league, raw, league_id, season, now)
    load("league_settings", settings)
    teams = transform_teams(league, league_id, season, now)
    load("teams", teams)
    stats = PLAYER_STATS
    points_check = None
    if points:
        load("league_scoring", transform_league_scoring(scoring, league_id, season, now))
        schedule = fetch_views(league_id, season, ["mMatchupScore"], cookies).get("schedule", [])
        load(
            "matchup_scores",
            transform_matchup_scores(schedule, current, league_id, season, now),
        )
        load(
            "pro_schedule",
            transform_pro_schedule(
                league.pro_schedule,
                raw.get("scheduleSettings", {}).get("matchupPeriods", {}),
                getattr(league, "matchup_ids", {}),
                league_id, season, now,
            ),
        )  # fmt: skip
        player_points = transform_player_points(
            rostered + free_agents, scoring, league_id, season, now
        )
        load("player_points", player_points)
        off = points_mismatches(player_points)
        points_check = {"checked": int((player_points["source"] == "espn").sum()),
                        "mismatched": int(len(off))}  # fmt: skip
        if len(off):
            print(f"league {league_id}: {len(off)} player windows differ from ESPN's points")
        stats = sorted(set(PLAYER_STATS) | {s["stat"] for s in scoring})
    else:
        load("league_categories", transform_league_categories(categories, league_id, season, now))
        load(
            "matchup_categories",
            transform_matchup_categories(league, periods, league_id, season, now),
            f"season = {season} AND {in_list('matchup_period', periods)}",
        )
    load("rosters", transform_rosters(league, league_id, season, now))
    load("free_agents", transform_free_agents(free_agents, league_id, season, now))
    load(
        "player_stats",
        transform_player_stats(rostered + free_agents, league_id, season, now, stats),
    )
    load("player_details", transform_player_details(details, league_id, season, now))
    names = {p.playerId: p.name for p in rostered + free_agents} | dict(league.player_map)
    new_txns = transform_transactions(topics, names, league_id, season, now)
    if not new_txns.empty:
        load("transactions", new_txns, in_list("txn_id", list(new_txns["txn_id"])))
    for past_season, (ids, records) in history.items():
        if ids:
            replace_rows(
                client, cfg.project, cfg.dataset, "player_seasons",
                transform_player_seasons({past_season: records}, ids, now),
                f"{in_list('player_id', ids)} AND history_season = {past_season}",
            )  # fmt: skip
    games = history_average(client, cfg, draft_ids)
    load("draft_pool", transform_draft_pool(draft_records, season, scoring, games, league_id, now))
    load(
        "draft_pool_stats",
        transform_draft_pool_stats(draft_records, season, stats, league_id, now),
    )
    load("draft_picks", transform_draft_picks(draft_detail, league_id, season, now))

    fields = {} if locked else {  # leagues registered before the format lock
        "format": espn_format, "format_season": season, "format_locked_at": now,
        "format_confirmed_by": "ingest",
    }  # fmt: skip
    return fields | {
        "league_name": raw.get("name"),
        "season": season,
        "scoring_type": scoring_type(raw["scoringSettings"]),
        "categories": categories,
        "scoring": scoring,
        "lineup_slots": lineup_slots(raw) if points else {},
        "bench_slots": bench_slots(raw) if points else 0,
        "draft": draft_settings(raw, draft_detail),
        "points_check": points_check,
        "format_mismatch": None,
        "teams": [  # plain Python values: Firestore can't store numpy types
            {"team_id": int(t.team_id), "team_name": str(n), "owner": o}
            for t, n, o in zip(league.teams, teams["team_name"], teams["owner"], strict=True)
        ],
        "current_matchup_period": current,
        "reg_season_matchup_periods": int(settings["reg_season_matchup_periods"].iloc[0]),
        "scores_final_through": max(0, current - 2),
        "activity_through_ms": max(
            [t["date"] for t in topics] + [int(league_doc.get("activity_through_ms") or 0)]
        ),
        "activity_needs_login": activity_needs_login,
        "last_ingested_at": now,
    }


def purge_league(league_doc: dict, client, db, cfg: Config) -> None:
    """Delete every row, registry entry and stored credential of a deleted league."""
    league_id = league_doc["league_id"]
    tables = LEAGUE_TABLES + [table_for(v) for v in MATERIALIZED_VIEWS]
    script = ";\n".join(
        f"DELETE FROM `{cfg.project}.{cfg.dataset}.{t}` WHERE league_id = {int(league_id)}"
        for t in tables
    )
    client.query(script).result()
    source = league_doc.get("credentials") or "public"
    if source.startswith("secret:"):
        from google.api_core.exceptions import NotFound
        from google.cloud import secretmanager

        try:
            secretmanager.SecretManagerServiceClient().delete_secret(
                name=f"projects/{cfg.project}/secrets/{source.removeprefix('secret:')}"
            )
        except NotFound:
            pass  # already removed by the commissioner
    registry.delete_league(db, league_id)
    print(f"league {league_id}: purged")


def main(env=os.environ) -> int:
    cfg = Config(env)
    client = bigquery.Client(project=cfg.project, location=cfg.location)
    db = registry.client(cfg.project)
    now = dt.datetime.now(dt.UTC)

    if cfg.task_index == 0:
        for league_doc in registry.leagues_to_purge(db):
            purge_league(league_doc, client, db, cfg)
    if cfg.purge_only:
        return 0

    leagues = registry.task_slice(
        registry.leagues_to_refresh(db, now, cfg.only_ids), cfg.task_index, cfg.task_count
    )
    print(f"task {cfg.task_index}/{cfg.task_count}: {len(leagues)} league(s)")
    done, failed = [], []
    for position, league_doc in enumerate(leagues):
        if position:
            time.sleep(random.uniform(*STAGGER_SECONDS))  # spread load on ESPN
        league_id = league_doc["league_id"]
        try:
            fields = ingest_league(league_doc, client, db, cfg, now)
            registry.record_success(db, league_id, fields)
            done.append(league_id)
            print(f"league {league_id}: ok")
        except FormatMismatch as error:  # waits for the site owner; data kept as it was
            registry.record_format_mismatch(db, league_id, error.espn_format, now)
            print(f"league {league_id}: format mismatch ({error})")
        except NeedsLogin as error:  # waits for the commissioner; not a job failure
            registry.record_needs_login(db, league_id, str(error), now)
            print(f"league {league_id}: needs a new ESPN login")
        except Exception as error:  # one league's failure mustn't stop the rest
            registry.record_error(db, league_id, str(error), now)
            failed.append(league_id)
            print(f"league {league_id}: FAILED: {error}", file=sys.stderr)

    if done:
        script = ";\n".join(refresh_statements(cfg.project, cfg.dataset, done))
        client.query(script).result()
        print(f"materialized {len(done)} league(s)")
    return 1 if failed and not done else 0


if __name__ == "__main__":
    sys.exit(main())
