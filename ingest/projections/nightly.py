"""The nightly NBA update (docs/whopDocs/nightly-update.md): the `nba-nightly` Cloud
Run Job, run each morning before `league-ingest`. Shared by every league; reads only
BallDontLie and ESPN's public player list, never a customer's league.

1. Games: the season's finished games since the last load (the last LOOKBACK_DAYS
   again, for late stat corrections) into `nba_player_games`. With none of the season
   loaded yet, the whole season so far.
2. Players: anyone in those games that `nba_players` doesn't know yet is added.
3. Linking: this season's players without an ESPN id are matched to ESPN's player
   list by name (people.match), then by name and current team (people.match_by_team),
   so a rookie or call-up reaches the pages once he plays. Ids already linked are never
   changed or reused.
4. The in-season blend: the preseason projection mixed with the season so far
   (blend.py), plus each player's projected bonus stats (bonus.py), written to
   `projections` as kind "blended". `league-ingest` reads the newest run, so the
   pages' "projected" window moves with the season. A player with games but no
   preseason projection (a rookie) starts from a league-average line instead, so one
   big night doesn't make him a star; his minutes follow his own after
   ROOKIE_PRIOR_GAMES games (tuned on the 2024-25 and 2025-26 rookie classes).
5. Games-played history: `player_seasons` (the last HISTORY_SEASONS seasons, by ESPN
   id) from our own games, in place of ESPN's.
6. Injuries: BallDontLie's current list into `nba_injuries`, and a dated copy into
   `nba_injury_history` (the day's list, kept).

Env: GCP_PROJECT_ID, SEASON (required); BIGQUERY_DATASET (league_lab); AS_OF (the
last day to load, default yesterday in US Eastern time, the NBA's calendar);
HISTORY_SEASONS (3).
"""

import datetime as dt
import os
import sys
from zoneinfo import ZoneInfo

import pandas as pd
from google.cloud import bigquery

from ingest.bigquery_load import in_list, replace_rows
from ingest.projections import people
from ingest.projections.blend import blend
from ingest.projections.bonus import add_bonus, bonus_rates
from ingest.projections.games import COLUMNS, STATS, from_columns, to_columns
from ingest.projections.model import DEFAULT, RATE_STATS, league_rates
from ingest.projections.run import MODEL_VERSION, PRESEASON, load_history
from ingest.projections.source import (
    Client,
    api_key,
    game_rows,
    games_left,
    injury_rows,
    player_rows,
)

LOOKBACK_DAYS = 3
# A rookie's minutes prior counts as 5 games, not blend's 15: tuned on the last two
# rookie classes, it cut the rest-of-season error after 9 days from 5.5 to 4.8
# fantasy points a game (his own early line alone: 7.9). His rates keep blend's
# 600-minute prior, which tested as well as any.
ROOKIE_PRIOR_GAMES = 5.0
BLENDED = "blended"
NBA_TIME = ZoneInfo("America/New_York")


def default_as_of(now: dt.datetime) -> dt.date:
    return now.astimezone(NBA_TIME).date() - dt.timedelta(days=1)


def load_start(last_loaded: dt.date | None, as_of: dt.date) -> dt.date | None:
    """First game date to (re)load: LOOKBACK_DAYS before the last loaded one, or None
    (the whole season) when nothing is loaded yet."""
    if last_loaded is None or pd.isna(last_loaded):
        return None
    return min(last_loaded, as_of) - dt.timedelta(days=LOOKBACK_DAYS)


def load_games(bdl, bq, project, dataset, season, as_of, now) -> pd.DataFrame:
    table = f"`{project}.{dataset}.nba_player_games`"
    last = next(iter(bq.query(
        f"SELECT MAX(game_date) AS last FROM {table} WHERE season = {int(season)}"
    ).result())).last  # fmt: skip
    start = load_start(last, as_of)
    rows = game_rows(bdl.game_stats(season, start, as_of), now)
    scope = f"season = {int(season)} AND game_date <= '{as_of}'"
    if start:
        scope += f" AND game_date >= '{start}'"
    replace_rows(bq, project, dataset, "nba_player_games", rows, scope)
    print(f"games: {rows['game_id'].nunique() if len(rows) else 0} games from "
          f"{start or 'the season start'} to {as_of}")  # fmt: skip
    return rows


def add_new_players(bdl, bq, project, dataset, season, now) -> int:
    table = f"`{project}.{dataset}"
    new = bq.query(
        f"SELECT DISTINCT g.player_id FROM {table}.nba_player_games` g "
        f"LEFT JOIN {table}.nba_players` n USING (player_id) "
        f"WHERE g.season = {int(season)} AND n.player_id IS NULL"
    ).to_dataframe()["player_id"]
    if new.empty:
        return 0
    rows = player_rows(bdl.players([int(i) for i in new]), now)
    replace_rows(bq, project, dataset, "nba_players", rows, in_list("player_id", list(new)))
    print(f"new players: {', '.join(rows['player_name'])}")
    return len(rows)


def links(players: pd.DataFrame, espn: pd.DataFrame) -> pd.DataFrame:
    """ESPN ids for `players` (player_id, player_name, draft_year, and team: his
    current team) from ESPN's list (espn_player_id, name, team), never one already
    linked to someone else: player_id, espn_player_id. By name first; then, for the
    rest, by name and team."""
    wiki = pd.DataFrame(columns=["item", "espn_player_id", "birth_date", "name"])
    found = people.match(players, wiki, espn)
    found = found.dropna(subset=["espn_player_id"])[["player_id", "espn_player_id"]]
    if "team" not in players or "team" not in espn:
        return found
    rest = players.loc[~players["player_id"].isin(found["player_id"])]
    free = espn.loc[~espn["espn_player_id"].isin(found["espn_player_id"])]
    by_team = people.match_by_team(rest[["player_id", "player_name", "team"]], free)
    return pd.concat([found, by_team], ignore_index=True)


def link_players(bq, project, dataset, season) -> pd.DataFrame:
    table = f"`{project}.{dataset}"
    players = bq.query(f"SELECT * FROM {table}.nba_players`").to_dataframe()
    playing = bq.query(
        f"SELECT DISTINCT player_id FROM {table}.nba_player_games` "
        f"WHERE season = {int(season)} AND min > 0"
    ).to_dataframe()["player_id"]
    need = players.loc[players["player_id"].isin(playing) & players["espn_player_id"].isna()]
    if need.empty:
        return need
    games = bq.query(
        f"SELECT player_id, season, game_date, team FROM {table}.nba_player_games` "
        f"WHERE season = {int(season)} AND min > 0"
    ).to_dataframe()
    current = teams_now(games, players[["player_id", "team"]], season)
    need = need.assign(team=need["player_id"].map(current))
    espn = people.fetch_espn_players(season)
    espn = espn.loc[~espn["espn_player_id"].isin(players["espn_player_id"].dropna())]
    found = links(need, espn)
    unlinked = need.loc[~need["player_id"].isin(found["player_id"]), "player_name"]
    if not found.empty:
        rows = need.drop(columns=["espn_player_id", "team"]).merge(found, on="player_id")
        rows = rows.merge(players[["player_id", "team"]], on="player_id")
        replace_rows(bq, project, dataset, "nba_players", rows,
                     in_list("player_id", list(rows["player_id"])))  # fmt: skip
    print(f"linked {len(found)} new ESPN ids; still unlinked: {', '.join(unlinked) or 'none'}")
    return found


def rookie_prior(seasons: pd.DataFrame, season: int, player_ids) -> pd.DataFrame:
    """A starting line for players without a preseason projection: last season's
    league-average rates at the model's prior minutes and games."""
    rates = league_rates(seasons, season - 1)
    line = pd.DataFrame(index=pd.Index(sorted(set(player_ids)), name="player_id"))
    line["GP"] = float(DEFAULT.games_prior)
    line["MIN"] = float(DEFAULT.mpg_prior)
    for stat in RATE_STATS:
        line[stat] = rates[stat] * DEFAULT.mpg_prior
    return line.reset_index()


def teams_now(games: pd.DataFrame, players: pd.DataFrame, season: int) -> pd.Series:
    """Each player's team: his latest game this season, else his listed team."""
    this = games.loc[games["season"] == season].sort_values("game_date")
    latest = this.groupby("player_id")["team"].last()
    listed = players.set_index("player_id")["team"]
    return latest.combine_first(listed)


def blended_rows(seasons, preseason, teams, left, season, made_at, bonus=None) -> pd.DataFrame:
    """The in-season projection for every player with a preseason line or games this
    season, in the projections table's shape. gp is his projected games for the whole
    season (played so far + projected the rest of the way), as in a preseason row.
    bonus: bonus_rates' (rates, league) for the bonus stats; without it they're empty."""
    to_date = seasons.loc[seasons["season"] == season]
    known = seasons.loc[seasons["season"] < season]
    missing = set(to_date["player_id"]) - set(preseason["player_id"])
    veterans = preseason[["player_id", "GP", *STATS]]
    rookies = rookie_prior(known, season, missing)

    def remaining(prior):
        ids = pd.Index(prior["player_id"])
        out = teams.reindex(ids).map(left).fillna(0).astype(float)
        out.index = ids
        return out

    def so_far(prior):
        return to_date.loc[to_date["player_id"].isin(prior["player_id"])]

    lines = pd.concat([
        blend(veterans, so_far(veterans), remaining(veterans)),
        blend(rookies, so_far(rookies), remaining(rookies), prior_games=ROOKIE_PRIOR_GAMES),
    ], ignore_index=True)  # fmt: skip
    played = to_date.set_index("player_id")["GP"].reindex(lines["player_id"]).fillna(0)
    lines["GP"] = lines["GP"].to_numpy() + played.to_numpy()
    if bonus is not None:
        lines = add_bonus(lines, *bonus)
    rows = to_columns(lines)
    rows["season"] = season
    ages = preseason.set_index("player_id").get("age")
    rows["age"] = rows["player_id"].map(ages) if ages is not None else None
    rows["history_minutes"] = None
    rows["made_at"] = made_at
    rows["model_version"] = MODEL_VERSION
    rows["kind"] = BLENDED
    return rows


def load_preseason(bq, project, dataset, season) -> pd.DataFrame:
    stats = ", ".join(COLUMNS[s] for s in [*STATS, "GP"])
    return from_columns(bq.query(
        f"SELECT player_id, age, {stats} FROM `{project}.{dataset}.projections` "
        f"WHERE season = {int(season)} AND kind = '{PRESEASON}' "
        f"AND model_version = '{MODEL_VERSION}' QUALIFY made_at = MAX(made_at) OVER ()"
    ).to_dataframe())  # fmt: skip


def make_blended(bdl, bq, project, dataset, season, as_of, now) -> int:
    seasons, _ = load_history(bq, project, dataset)
    preseason = load_preseason(bq, project, dataset, season)
    if preseason.empty:
        raise RuntimeError(f"no preseason projections for {season}: run make_projections.py")
    table = f"`{project}.{dataset}"
    games = bq.query(
        f"SELECT player_id, season, game_date, team FROM {table}.nba_player_games` "
        f"WHERE season = {int(season)} AND min > 0"
    ).to_dataframe()
    players = bq.query(f"SELECT player_id, team FROM {table}.nba_players`").to_dataframe()
    left = games_left(bdl.games(season), as_of)
    stats = ", ".join(COLUMNS[s] for s in [*STATS, "PF"])
    recent = from_columns(bq.query(
        f"SELECT player_id, season, {stats} FROM {table}.nba_player_games` "
        f"WHERE season BETWEEN {int(season) - 2} AND {int(season)} AND min > 0"
    ).to_dataframe())  # fmt: skip
    rows = blended_rows(seasons, preseason, teams_now(games, players, season), left, season, now,
                        bonus_rates(recent, season))  # fmt: skip
    scope = (f"season = {int(season)} AND kind = '{BLENDED}' "
             f"AND DATE(made_at) = '{now.date()}'")  # fmt: skip
    replace_rows(bq, project, dataset, "projections", rows, scope)
    return len(rows)


def history_rows(seasons: pd.DataFrame, players: pd.DataFrame, season: int,
                 history_seasons: int, now) -> pd.DataFrame:  # fmt: skip
    """player_seasons rows (by ESPN id): games played in each of the past seasons."""
    past = seasons.loc[seasons["season"].between(season - history_seasons, season - 1)]
    ids = players.dropna(subset=["espn_player_id"]).set_index("player_id")["espn_player_id"]
    rows = past.loc[past["player_id"].isin(ids.index), ["player_id", "season", "GP"]]
    return pd.DataFrame({
        "player_id": rows["player_id"].map(ids).astype("int64").to_numpy(),
        "history_season": rows["season"].astype("int64").to_numpy(),
        "games_played": rows["GP"].astype(float).to_numpy(),
        "ingested_at": now,
    })  # fmt: skip


def write_history(bq, project, dataset, season, history_seasons, now) -> int:
    seasons, _ = load_history(bq, project, dataset)
    players = bq.query(
        f"SELECT player_id, espn_player_id FROM `{project}.{dataset}.nba_players`"
    ).to_dataframe()
    rows = history_rows(seasons, players, season, history_seasons, now)
    return replace_rows(bq, project, dataset, "player_seasons", rows, "TRUE")


def injury_history_rows(rows: pd.DataFrame, day: dt.date) -> pd.DataFrame:
    return rows.drop(columns="ingested_at").assign(snapshot_date=day)


def write_injuries(bdl, bq, project, dataset, now) -> int:
    rows = injury_rows(bdl.injuries(), now)
    if rows.empty:  # an empty list is more likely an outage than a healthy league
        print("injuries: BallDontLie returned none; keeping yesterday's")
        return 0
    day = now.astimezone(NBA_TIME).date()
    replace_rows(bq, project, dataset, "nba_injury_history", injury_history_rows(rows, day),
                 f"snapshot_date = '{day}'")  # fmt: skip
    return replace_rows(bq, project, dataset, "nba_injuries", rows, "TRUE")


def main(env=os.environ) -> int:
    project = env["GCP_PROJECT_ID"]
    dataset = env.get("BIGQUERY_DATASET", "league_lab")
    season = int(env["SEASON"])
    now = dt.datetime.now(dt.UTC)
    as_of = dt.date.fromisoformat(env["AS_OF"]) if env.get("AS_OF") else default_as_of(now)
    history_seasons = int(env.get("HISTORY_SEASONS", "3"))
    bq = bigquery.Client(project=project, location=env.get("BIGQUERY_LOCATION", "us-west1"))
    bdl = Client(api_key(project))

    load_games(bdl, bq, project, dataset, season, as_of, now)
    add_new_players(bdl, bq, project, dataset, season, now)
    link_players(bq, project, dataset, season)
    print(f"blended projections: {make_blended(bdl, bq, project, dataset, season, as_of, now)}")
    write_history(bq, project, dataset, season, history_seasons, now)
    write_injuries(bdl, bq, project, dataset, now)
    return 0


if __name__ == "__main__":
    sys.exit(main())
