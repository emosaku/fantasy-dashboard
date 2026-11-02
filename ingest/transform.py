"""ESPN objects and raw records -> DataFrames matching sql/ddl/*.sql, for one league.

Every row carries league_id and season. Field shapes come from inspecting the real
API (see the single-league build's notebooks and docs), not espn-api's docs.
"""

import datetime as dt
import hashlib

import pandas as pd
from espn_api.basketball.constant import ACTIVITY_MAP, POSITION_MAP, PRO_TEAM_MAP

from ingest.catalog import PLAYER_STATS, scoring_type, uncounted_stats

# ESPN's stat-window keys -> this project's stat_window. Only read for the points
# check (transform_player_points): every stored window is ours, built from BallDontLie
# games (transform_window_stats, transform_window_points) and our projections
# (transform_projected_stats, transform_projected_points). ESPN's own projections
# ("_projected") are never read.
WINDOW_SUFFIXES = {
    "_total": "season",
    "_last_30": "last_30",
    "_last_15": "last_15",
    "_last_7": "last_7",
}
PROJECTED = "projected"
NOT_STARTING = {"BE", "IR", "Rookie", ""}  # eligibleSlots that aren't lineup spots
POINTS_TOLERANCE = 0.1  # our stat x points vs ESPN's applied average, per game
# Alert when more than this share of a league's checked player windows is off (and at
# least ALERT_MIN_CHECKED were checked): normal is the providers' small stat
# corrections, about 10-12% early in the season and shrinking as games accumulate.
ALERT_SHARE = 0.25
ALERT_MIN_CHECKED = 50
ALERT_MARKER = "POINTS_CHECK_ALERT"  # the log-based alert matches this text


def _base(league_id: int, season: int, ingested_at: dt.datetime) -> dict:
    return {"league_id": league_id, "season": season, "ingested_at": ingested_at}


def transform_league_settings(league, raw_settings, league_id, season, ingested_at):
    schedule = raw_settings.get("scheduleSettings", {})
    return pd.DataFrame(
        [
            {
                **_base(league_id, season, ingested_at),
                "league_name": raw_settings.get("name"),
                "scoring_type": scoring_type(raw_settings["scoringSettings"]),
                "team_count": len(league.teams),
                "current_matchup_period": league.currentMatchupPeriod,
                "reg_season_matchup_periods": schedule.get("matchupPeriodCount")
                or league.settings.reg_season_count,
                "playoff_team_count": schedule.get("playoffTeamCount"),
            }
        ]
    )


def transform_league_categories(categories, league_id, season, ingested_at):
    return pd.DataFrame([{**_base(league_id, season, ingested_at), **c} for c in categories])


def _owner_name(owner: dict) -> str:
    """The manager's real name, as ESPN's site shows it; the ESPN username only when
    the account has no name. ESPN keeps stray spaces, so strip them."""
    full = f"{(owner.get('firstName') or '').strip()} {(owner.get('lastName') or '').strip()}"
    return full.strip() or owner.get("displayName", "")


def transform_teams(league, league_id, season, ingested_at):
    return pd.DataFrame(
        [
            {
                **_base(league_id, season, ingested_at),
                "team_id": team.team_id,
                "team_name": (team.team_name or "").strip() or f"Team {team.team_id}",
                "owner": ", ".join(_owner_name(o) for o in (team.owners or [])) or None,
                "wins": team.wins,
                "losses": team.losses,
                "points_for": float(getattr(team, "points_for", 0) or 0),
                "points_against": float(getattr(team, "points_against", 0) or 0),
                "ties": getattr(team, "ties", 0),
                "standing": getattr(team, "standing", None),
            }
            for team in league.teams
        ]
    )


def transform_matchup_categories(league, periods, league_id, season, ingested_at):
    """Both sides of every matchup in these periods: each box score is one row per
    side per stat, each with its own team_id / opponent_id."""
    rows = []
    for period in periods:
        for box in league.box_scores(matchup_period=period):
            if box.home_team is None or box.away_team is None:
                continue  # bye week
            for team, opponent, stats in (
                (box.home_team, box.away_team, box.home_stats),
                (box.away_team, box.home_team, box.away_stats),
            ):
                for category, stat in (stats or {}).items():
                    rows.append(
                        {
                            **_base(league_id, season, ingested_at),
                            "matchup_period": period,
                            "team_id": team.team_id,
                            "opponent_id": opponent.team_id,
                            "category": category,
                            "value": float(stat["value"]),
                            "result": stat.get("result"),
                        }
                    )
    return pd.DataFrame(rows)


def eligible_slots(player) -> str:
    """The lineup slots a player can start in, comma-joined (PG,G,UT ...)."""
    slots = getattr(player, "eligibleSlots", None) or []
    return ",".join(s for s in slots if s not in NOT_STARTING)


def transform_rosters(league, league_id, season, ingested_at):
    return pd.DataFrame(
        [
            {
                **_base(league_id, season, ingested_at),
                "team_id": team.team_id,
                "player_id": player.playerId,
                "player_name": player.name,
                "position": getattr(player, "position", None),
                "lineup_slot": getattr(player, "lineupSlot", None),
                "injury_status": getattr(player, "injuryStatus", None),
                "expected_return_date": getattr(player, "expected_return_date", None),
                "pro_team": getattr(player, "proTeam", None),
                "eligible_slots": eligible_slots(player),
            }
            for team in league.teams
            for player in team.roster
        ]
    )


def transform_free_agents(free_agents, league_id, season, ingested_at):
    return pd.DataFrame(
        [
            {
                **_base(league_id, season, ingested_at),
                "player_id": player.playerId,
                "player_name": player.name,
                "position": getattr(player, "position", None),
                "pro_team": getattr(player, "proTeam", None),
                "injury_status": getattr(player, "injuryStatus", None),
                "eligible_slots": eligible_slots(player),
            }
            for player in free_agents
        ]
    )


def _activity_team(msg: dict):
    """Which team a message is about -- including "for" on a lineup move, which
    espn_api leaves blank."""
    if msg["messageTypeId"] == 244:
        return msg.get("from")
    if msg["messageTypeId"] in (239, 188):
        return msg.get("for")
    return msg.get("to")


def transform_transactions(topics, player_names, league_id, season, ingested_at):
    rows = []
    for topic in topics:
        txn_date = dt.datetime.fromtimestamp(topic["date"] / 1000, tz=dt.UTC)
        for msg in topic.get("messages", []):
            action = ACTIVITY_MAP.get(msg["messageTypeId"])
            if action is None:
                continue
            team_id = _activity_team(msg)
            player_id = msg.get("targetId")
            player_name = player_names.get(player_id, "")
            detail = None
            if action == "MOVED":
                slot_from = POSITION_MAP.get(msg.get("from"), "?")
                detail = f"{slot_from} to {POSITION_MAP.get(msg.get('to'), '?')}"
            # Deterministic id (ESPN has none): same action, same id, every run.
            key = f"{league_id}:{topic['date']}:{team_id}:{action}:{player_name}"
            rows.append(
                {
                    **_base(league_id, season, ingested_at),
                    "txn_id": hashlib.sha256(key.encode()).hexdigest()[:32],
                    "txn_date": txn_date,
                    "team_id": team_id,
                    "action": action,
                    "player_id": player_id,
                    "player_name": player_name,
                    "detail": detail,
                }
            )
    return pd.DataFrame(rows)


def transform_player_details(records, league_id, season, ingested_at):
    rows = []
    for record in records:
        returns = record.get("expectedReturnDate")
        rows.append(
            {
                **_base(league_id, season, ingested_at),
                "player_id": record["id"],
                "injured": record.get("injured"),
                "injury_status": record.get("injuryStatus"),
                "expected_return_date": dt.date(*returns[:3]) if returns else None,
            }
        )
    return pd.DataFrame(rows)


# --- Points leagues -------------------------------------------------------------------


def transform_league_scoring(scoring, league_id, season, ingested_at):
    return pd.DataFrame([{**_base(league_id, season, ingested_at), **s} for s in scoring])


def lineup_slots(raw_settings: dict) -> dict[str, int]:
    """The league's starting lineup: {slot: count} (PG, G, UT ...), bench and IR left
    out, in ESPN's slot order."""
    counts = (raw_settings.get("rosterSettings") or {}).get("lineupSlotCounts") or {}
    out = {}
    for slot_id, count in sorted(counts.items(), key=lambda kv: int(kv[0])):
        name = POSITION_MAP.get(int(slot_id), "")
        if count and name not in NOT_STARTING:
            out[name] = int(count)
    return out


def bench_slots(raw_settings: dict) -> int:
    """How many bench spots the league has (lineupSlotCounts' BE)."""
    counts = (raw_settings.get("rosterSettings") or {}).get("lineupSlotCounts") or {}
    return int(sum(c for s, c in counts.items() if POSITION_MAP.get(int(s)) == "BE"))


def computed_points(avg: dict | None, scoring: list[dict]) -> float | None:
    """Fantasy points per game from a per-game stat line and the league's values;
    None without a line. Games played is worth its points once per game (the line's GP
    counts games in the window); a stat the line doesn't carry counts 0."""
    if not avg:
        return None
    return sum(
        (1.0 if s["stat"] == "GP" else float(avg.get(s["stat"]) or 0)) * s["points"]
        for s in scoring
    )


def transform_player_points(players, scoring, league_id, season, ingested_at):
    """ESPN's fantasy points per stat window (appliedAverage, appliedTotal: bonuses
    included), with stat x points from ESPN's own line beside them, and the part of
    ESPN's points from stats we can't count (uncounted_per_game: ejections ...). Not
    stored: only the points check (points_mismatches) reads it, against ours."""
    uncounted = [s for s in scoring if s["stat"] in set(uncounted_stats(scoring))]
    rows, seen = [], set()
    for player in players:
        if player.playerId in seen:
            continue
        seen.add(player.playerId)
        for suffix, window in WINDOW_SUFFIXES.items():
            data = player.stats.get(f"{season}{suffix}")
            if not data:
                continue
            ours = computed_points(data.get("avg"), scoring)
            games = (data.get("total") or {}).get("GP") or (data.get("avg") or {}).get("GP")
            espn_avg = float(data.get("applied_avg") or 0)
            espn_total = float(data.get("applied_total") or 0)
            if espn_avg:
                fp, total, source = espn_avg, espn_total, "espn"
            elif ours is not None:
                fp, source = ours, "computed"
                total = ours * float(games) if games else None
            else:
                continue
            rows.append(
                {
                    **_base(league_id, season, ingested_at),
                    "player_id": player.playerId,
                    "stat_window": window,
                    "fp_per_game": float(fp),
                    "fp_total": None if total is None else float(total),
                    "games": None if games is None else float(games),
                    "computed_per_game": ours,
                    "uncounted_per_game": computed_points(data.get("avg"), uncounted) or 0.0,
                    "source": source,
                }
            )
    return pd.DataFrame(rows)


def _projected_pool(lines: pd.DataFrame, player_ids) -> pd.DataFrame:
    """Our projected lines (indexed by ESPN player id) for the league's pool players."""
    if lines is None or lines.empty:
        return pd.DataFrame()
    return lines.loc[lines.index.intersection(pd.Index(player_ids, dtype="int64"))]


def transform_projected_stats(lines, player_ids, league_id, season, ingested_at,
                              stats=PLAYER_STATS):  # fmt: skip
    """Our projections as the "projected" window, in transform_player_stats' shape: one
    row per pool player we project x stat. lines: per-game lines by ESPN player id
    (ingest/projections/run.py's latest), GP = projected games."""
    rows = []
    for player_id, line in _projected_pool(lines, player_ids).iterrows():
        for stat in stats:
            value = line.get(stat)
            if value is not None and pd.notna(value):
                rows.append(
                    {
                        **_base(league_id, season, ingested_at),
                        "player_id": int(player_id),
                        "stat_window": PROJECTED,
                        "stat": stat,
                        "value": float(value),
                    }
                )
    return pd.DataFrame(rows)


def transform_projected_points(lines, player_ids, scoring, league_id, season, ingested_at):
    """Our projections as the "projected" window of player_points: the league's point
    values times our per-game line (stats the line doesn't carry count 0)."""
    rows = []
    for player_id, line in _projected_pool(lines, player_ids).iterrows():
        avg = {k: v for k, v in line.items() if pd.notna(v)}
        fp = computed_points(avg, scoring)
        games = avg.get("GP")
        rows.append(
            {
                **_base(league_id, season, ingested_at),
                "player_id": int(player_id),
                "stat_window": PROJECTED,
                "fp_per_game": float(fp),
                "fp_total": float(fp * games) if games else None,
                "games": float(games) if games else None,
                "computed_per_game": float(fp),
                "source": "computed",
            }
        )
    return pd.DataFrame(rows)


def points_mismatches(espn: pd.DataFrame, ours: pd.DataFrame) -> pd.DataFrame:
    """Player windows where ESPN's applied average and our fantasy points (our games x
    the league's values) differ by more than POINTS_TOLERANCE: a misread scoring rule, a
    game one side has and the other doesn't, or a bonus stat (double-doubles) our line
    doesn't carry. espn: transform_player_points; ours: transform_window_points. The
    points ESPN gives for stats we can't count (uncounted_per_game) are expected to be
    missing from ours, so they're taken off ESPN's side first: only unexplained gaps
    are flagged. Only windows where both count the same games are compared (comparable):
    during the day ESPN already has tonight's games and ours don't."""
    if espn.empty or ours.empty:
        return pd.DataFrame(columns=["player_id", "stat_window", "espn", "ours"])
    keys = ["player_id", "stat_window"]
    espn = comparable(espn, ours).copy()
    if "uncounted_per_game" in espn:
        espn["fp_per_game"] = espn["fp_per_game"] - espn["uncounted_per_game"].fillna(0)
    both = espn[[*keys, "fp_per_game"]].merge(
        ours[[*keys, "fp_per_game"]], on=keys, suffixes=("_espn", "_ours")
    )
    both = both.rename(columns={"fp_per_game_espn": "espn", "fp_per_game_ours": "ours"})
    return both.loc[(both["espn"] - both["ours"]).abs() > POINTS_TOLERANCE]


def comparable(espn: pd.DataFrame, ours: pd.DataFrame) -> pd.DataFrame:
    """ESPN's own-points rows (source espn) whose window has the same games as ours."""
    keys = ["player_id", "stat_window"]
    rows = espn.loc[espn["source"] == "espn"]
    if ours.empty:
        return rows.iloc[0:0]
    games = rows[[*keys, "games"]].merge(ours[[*keys, "games"]], on=keys, suffixes=("", "_ours"))
    same = games.loc[games["games"] == games["games_ours"], keys]
    return rows.merge(same, on=keys)


def points_alert(league_id: int, check: dict | None) -> str | None:
    """The alert line for a league whose points check is off too often, else None."""
    if not check or check["checked"] < ALERT_MIN_CHECKED:
        return None
    share = check["mismatched"] / check["checked"]
    if share <= ALERT_SHARE:
        return None
    return (f"{ALERT_MARKER} league {league_id}: {check['mismatched']} of {check['checked']} "
            f"player windows ({share:.0%}) differ from ESPN's fantasy points by more than "
            f"{POINTS_TOLERANCE} a game; a scoring rule may be misread")  # fmt: skip


def _pool_windows(windows: pd.DataFrame, player_ids) -> pd.DataFrame:
    if windows is None or windows.empty:
        return pd.DataFrame(columns=["player_id", "stat_window", "stat", "value"])
    return windows.loc[windows["player_id"].isin(set(int(p) for p in player_ids))]


def transform_window_stats(windows, player_ids, league_id, season, ingested_at,
                           stats=PLAYER_STATS):  # fmt: skip
    """Our actual-stat windows (season, last 30/15/7 days) for the league's pool, in
    player_stats' shape. windows: run.windows (long, by ESPN player id). A stat our
    games don't carry (one only a points league scores) has no row."""
    rows = _pool_windows(windows, player_ids)
    rows = rows.loc[rows["stat"].isin(stats)]
    out = rows.assign(league_id=league_id, season=season, ingested_at=ingested_at)
    out["player_id"] = out["player_id"].astype("int64")
    out["value"] = out["value"].astype(float)
    return out[["league_id", "season", "ingested_at", "player_id", "stat_window", "stat",
                "value"]].reset_index(drop=True)  # fmt: skip


def transform_window_points(windows, player_ids, scoring, league_id, season, ingested_at):
    """Fantasy points per window from our actual stats: the league's values times our
    per-game line (stats the line doesn't carry count 0), source "computed"."""
    rows = []
    wide = _pool_windows(windows, player_ids).pivot_table(
        index=["player_id", "stat_window"], columns="stat", values="value", aggfunc="first"
    )
    for (player_id, window), line in wide.iterrows():
        avg = {k: v for k, v in line.items() if pd.notna(v)}
        fp = computed_points(avg, scoring)
        games = avg.get("GP")
        rows.append(
            {
                **_base(league_id, season, ingested_at),
                "player_id": int(player_id),
                "stat_window": window,
                "fp_per_game": float(fp),
                "fp_total": float(fp * games) if games else None,
                "games": float(games) if games else None,
                "computed_per_game": float(fp),
                "source": "computed",
            }
        )
    return pd.DataFrame(rows)


def apply_injuries(frame: pd.DataFrame, injuries: pd.DataFrame | None,
                   return_column: str | None = "expected_return_date") -> pd.DataFrame:  # fmt: skip
    """Injury status (and return date) from our list (run.injuries, by ESPN id) in place
    of ESPN's: a player not on it is ACTIVE. With no list at all (none loaded yet),
    the status is unknown (None) rather than ESPN's."""
    if frame.empty:
        return frame
    out = frame.copy()
    listed = injuries if injuries is not None else pd.DataFrame(columns=["status", "return_date"])
    status = out["player_id"].map(listed["status"])
    out["injury_status"] = status.fillna("ACTIVE") if injuries is not None else None
    if return_column:
        out[return_column] = out["player_id"].map(listed["return_date"]).astype("object")
        out[return_column] = out[return_column].where(out[return_column].notna(), None)
    if "injured" in out:
        out["injured"] = (out["injury_status"] != "ACTIVE") if injuries is not None else None
    return out


def transform_matchup_scores(schedule, current_period, league_id, season, ingested_at):
    """Every matchup of the season, played or not, one row per side: weekly points
    (ESPN's live total for the current week), the opponent, and whether it's a playoff
    game. Byes are skipped."""
    rows = []
    for match in schedule:
        home, away = match.get("home") or {}, match.get("away") or {}
        if not home or not away:
            continue
        period = int(match["matchupPeriodId"])
        for side, other in ((home, away), (away, home)):
            live = side.get("totalPointsLive")
            points = (
                live if period == current_period and live is not None else side.get("totalPoints")
            )
            rows.append(
                {
                    **_base(league_id, season, ingested_at),
                    "matchup_period": period,
                    "team_id": int(side["teamId"]),
                    "opponent_id": int(other["teamId"]),
                    "points": float(points or 0),
                    "opponent_points": float(
                        (other.get("totalPointsLive") if period == current_period else None)
                        or other.get("totalPoints")
                        or 0
                    ),
                    "is_playoff": (match.get("playoffTierType") or "NONE") != "NONE",
                    "winner": match.get("winner"),
                    "is_home": side is home,
                }
            )
    return pd.DataFrame(rows)


def week_of(day: dt.date, opening_day: dt.date) -> int:
    """ESPN's base week for a date: weeks run Monday to Sunday, week 1 holding
    opening night."""
    first_monday = opening_day - dt.timedelta(days=opening_day.weekday())
    return (day - first_monday).days // 7 + 1


def transform_pro_schedule(pro_schedule, matchup_periods, played_days, league_id, season,
                           ingested_at):  # fmt: skip
    """Every NBA game as one row per team: its date, ESPN's scoring period (day) and
    the league's matchup period. pro_schedule is espn-api's {pro team id: {scoring
    period: [game]}}; matchup_periods ESPN's scheduleSettings.matchupPeriods (matchup ->
    base weeks); played_days espn-api's matchup_ids (matchup -> the exact scoring
    periods, known once a week is played), which win over the Monday-week rule."""
    games = []
    for team_id, by_period in (pro_schedule or {}).items():
        if not team_id:
            continue
        for scoring_period, entries in (by_period or {}).items():
            for game in entries or []:
                when = dt.datetime.fromtimestamp(game["date"] / 1000, tz=dt.UTC)
                # ESPN dates games in US Eastern time; tip-offs are 7 pm ET or later.
                day = (when - dt.timedelta(hours=5)).date()
                games.append((int(team_id), int(scoring_period), day))
    if not games:
        return pd.DataFrame()
    opening_day = min(day for _, _, day in games)
    week_to_matchup = {
        int(week): int(matchup) for matchup, weeks in matchup_periods.items() for week in weeks
    }
    exact = {int(sp): int(m) for m, sps in (played_days or {}).items() for sp in sps}
    rows = []
    for team_id, scoring_period, day in games:
        matchup = exact.get(scoring_period) or week_to_matchup.get(week_of(day, opening_day))
        rows.append(
            {
                **_base(league_id, season, ingested_at),
                "pro_team": PRO_TEAM_MAP.get(team_id, str(team_id)),
                "scoring_period": scoring_period,
                "game_date": day,
                "matchup_period": matchup,
            }
        )
    return pd.DataFrame(rows).drop_duplicates(["pro_team", "scoring_period"])
