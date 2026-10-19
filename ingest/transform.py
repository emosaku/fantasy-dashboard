"""ESPN objects and raw records -> DataFrames matching sql/ddl/*.sql, for one league.

Every row carries league_id and season. Field shapes come from inspecting the real
API (see the single-league build's notebooks and docs), not espn-api's docs.
"""

import datetime as dt
import hashlib

import pandas as pd
from espn_api.basketball.constant import ACTIVITY_MAP, POSITION_MAP, PRO_TEAM_MAP

from ingest.catalog import PLAYER_STATS, scoring_type

# ESPN's stat-window keys -> this project's stat_window.
WINDOW_SUFFIXES = {
    "_total": "season",
    "_last_30": "last_30",
    "_last_15": "last_15",
    "_last_7": "last_7",
    "_projected": "projected",
}
GAMES_PLAYED_STAT = "42"
NOT_STARTING = {"BE", "IR", "Rookie", ""}  # eligibleSlots that aren't lineup spots
POINTS_TOLERANCE = 0.1  # our stat x points vs ESPN's applied average, per game


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


def transform_player_stats(players, league_id, season, ingested_at, stats=PLAYER_STATS):
    """Per-game averages, long: one row per player x window x stat, for every stat
    the category catalog can use (plus GP), and any other stat a points league scores.
    Windows ESPN hasn't filled are skipped."""
    rows, seen = [], set()
    for player in players:
        if player.playerId in seen:
            continue
        seen.add(player.playerId)
        for suffix, window in WINDOW_SUFFIXES.items():
            data = player.stats.get(f"{season}{suffix}")
            if not data or "avg" not in data:
                continue
            for stat in stats:
                value = data["avg"].get(stat)
                if value is not None:
                    rows.append(
                        {
                            **_base(league_id, season, ingested_at),
                            "player_id": player.playerId,
                            "stat_window": window,
                            "stat": stat,
                            "value": float(value),
                        }
                    )
    return pd.DataFrame(rows)


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
                "season_outlook": record.get("seasonOutlook") or None,
            }
        )
    return pd.DataFrame(rows)


def _games_played(record: dict, season: int):
    for stat in record.get("stats", []):
        if (
            stat.get("seasonId") == season
            and stat.get("statSourceId") == 0
            and stat.get("statSplitTypeId") == 0
        ):
            return stat.get("stats", {}).get(GAMES_PLAYED_STAT)
    return None


def transform_player_seasons(records_by_season, player_ids, ingested_at):
    """Games played per past season for these players. A player with no line that
    season gets a row with NULL, so he isn't fetched again tomorrow."""
    rows = []
    for history_season, records in records_by_season.items():
        found = {r["id"]: _games_played(r, history_season) for r in records}
        for player_id in player_ids:
            games = found.get(player_id)
            rows.append(
                {
                    "player_id": player_id,
                    "history_season": history_season,
                    "games_played": None if games is None else float(games),
                    "ingested_at": ingested_at,
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
    None without a line."""
    if not avg:
        return None
    return sum(float(avg.get(s["stat"]) or 0) * s["points"] for s in scoring)


def transform_player_points(players, scoring, league_id, season, ingested_at):
    """Each player's fantasy points per stat window: ESPN's own numbers (appliedAverage,
    appliedTotal: bonuses included), with our stat x points beside them. ESPN's are used
    whenever it sent them; `source` says which one fp_per_game is."""
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
                    "source": source,
                }
            )
    return pd.DataFrame(rows)


def points_mismatches(points: pd.DataFrame) -> pd.DataFrame:
    """Player windows where ESPN's applied average and our stat x points differ by
    more than POINTS_TOLERANCE: a sign a scoring rule was misread (or a bonus stat,
    like double-doubles, that the per-game line doesn't carry)."""
    if points.empty:
        return points
    both = points.loc[(points["source"] == "espn") & points["computed_per_game"].notna()]
    gap = (both["fp_per_game"] - both["computed_per_game"]).abs()
    return both.loc[gap > POINTS_TOLERANCE]


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
