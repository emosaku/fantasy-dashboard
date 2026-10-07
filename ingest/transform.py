"""Turns espn-api objects into DataFrames matching sql/ddl/*.sql exactly.

Field shapes here come from inspecting the real API (notebooks/01_explore_espn_api.py),
not from espn-api's docs -- field names shift between library versions.
"""

import datetime as dt
import hashlib
import json

import pandas as pd
from espn_api.basketball import League
from espn_api.basketball.constant import ACTIVITY_MAP, POSITION_MAP

# ESPN's stat-window keys are "{season}_total"/"_last_30"/"_last_15"/"_last_7"/
# "_projected"; only "_projected" carries a populated avg/total breakdown before any
# games are played, which is why 'projected' is included as its own stat_window.
WINDOW_SUFFIXES = {
    "_total": "season",
    "_last_30": "last_30",
    "_last_15": "last_15",
    "_last_7": "last_7",
    "_projected": "projected",
}

# ESPN's per-category keys (home_stats/away_stats, player.stats[...]['avg']) to this
# project's column names. GP isn't a category: it's the window's game count (ESPN
# puts the plain count in the avg block), used to blend season stats with projections.
CATEGORY_COLUMNS = {
    "PTS": "pts",
    "REB": "reb",
    "AST": "ast",
    "STL": "stl",
    "BLK": "blk",
    "3PM": "fg3m",
    "3PA": "fg3a",
    "FGM": "fgm",
    "FGA": "fga",
    "FTM": "ftm",
    "FTA": "fta",
    "TO": "turnovers",
    "GP": "gp",
}


def _owner_name(owner: dict) -> str:
    """The manager's real name, as ESPN's site shows it. displayName is the ESPN
    username (often "ESPNFAN6474865950"), kept only as a fallback for a manager with
    no name on the account. ESPN keeps stray spaces ("Timothy "), so strip them."""
    full = f"{(owner.get('firstName') or '').strip()} {(owner.get('lastName') or '').strip()}"
    return full.strip() or owner.get("displayName", "")


def transform_teams(
    league: League, season: int, snapshot_date: dt.date, ingested_at: dt.datetime
) -> pd.DataFrame:
    rows = []
    for team in league.teams:
        owners = team.owners or []
        owner = ", ".join(_owner_name(o) for o in owners) or None
        rows.append(
            {
                "snapshot_date": snapshot_date,
                "season": season,
                "team_id": team.team_id,
                "team_name": team.team_name,
                "owner": owner,
                "wins": team.wins,
                "losses": team.losses,
                "ties": getattr(team, "ties", 0),
                "standing": getattr(team, "standing", None),
                "ingested_at": ingested_at,
            }
        )
    return pd.DataFrame(rows)


def trade_deadline(league: League) -> pd.Timestamp | None:
    """ESPN's trade deadline (epoch milliseconds; 0 when the league has none)."""
    ms = getattr(league.settings, "trade_deadline", 0) or 0
    return pd.Timestamp(ms, unit="ms", tz="UTC") if ms else None


def transform_league_status(
    league: League, season: int, snapshot_date: dt.date, ingested_at: dt.datetime
) -> pd.DataFrame:
    """Where the season stands today: the current matchup period and how many
    regular-season periods there are. v_season_projection splits finished weeks
    (actual results) from the rest (projected) on these. The trade deadline and
    review period tell the Trade Analyzer whether a three-team deal's two trades can
    both clear in time."""
    return pd.DataFrame(
        [
            {
                "snapshot_date": snapshot_date,
                "season": season,
                "current_matchup_period": league.currentMatchupPeriod,
                "reg_season_matchup_periods": league.settings.reg_season_count,
                "playoff_team_count": getattr(league.settings, "playoff_team_count", None),
                "trade_deadline": trade_deadline(league),
                "trade_review_hours": getattr(league.settings, "trade_revision_hours", None),
                "ingested_at": ingested_at,
            }
        ]
    )


def transform_matchup_categories(
    league: League, season: int, current_matchup_period: int, ingested_at: dt.datetime
) -> pd.DataFrame:
    rows = []
    for period in range(1, current_matchup_period + 1):
        for box in league.box_scores(matchup_period=period):
            if box.home_team is None or box.away_team is None:
                continue  # bye week
            sides = (
                (box.home_team, box.away_team, box.home_stats),
                (box.away_team, box.home_team, box.away_stats),
            )
            for team, opponent, stats in sides:
                for category, stat in stats.items():
                    rows.append(
                        {
                            "season": season,
                            "matchup_period": period,
                            "team_id": team.team_id,
                            "opponent_id": opponent.team_id,
                            "category": category,
                            "value": float(stat["value"]),
                            "result": stat["result"],
                            "ingested_at": ingested_at,
                        }
                    )
    return pd.DataFrame(rows)


def transform_rosters(
    league: League, season: int, snapshot_date: dt.date, ingested_at: dt.datetime
) -> pd.DataFrame:
    rows = []
    for team in league.teams:
        for player in team.roster:
            rows.append(
                {
                    "snapshot_date": snapshot_date,
                    "season": season,
                    "team_id": team.team_id,
                    "player_id": player.playerId,
                    "player_name": player.name,
                    "position": getattr(player, "position", None),
                    "lineup_slot": getattr(player, "lineupSlot", None),
                    "injury_status": getattr(player, "injuryStatus", None),
                    # ESPN's estimate, often empty; the projection falls back to defaults.
                    "expected_return_date": getattr(player, "expected_return_date", None),
                    "ingested_at": ingested_at,
                }
            )
    return pd.DataFrame(rows)


def transform_free_agents(
    free_agents: list, season: int, snapshot_date: dt.date, ingested_at: dt.datetime
) -> pd.DataFrame:
    """The day's top free agents (league.free_agents(size=N)): the waiver pool the
    Trade & Waiver Analyzer recommends from, and part of the z-score player pool."""
    return pd.DataFrame(
        [
            {
                "snapshot_date": snapshot_date,
                "season": season,
                "player_id": player.playerId,
                "player_name": player.name,
                "position": getattr(player, "position", None),
                "pro_team": getattr(player, "proTeam", None),
                "injury_status": getattr(player, "injuryStatus", None),
                "ingested_at": ingested_at,
            }
            for player in free_agents
        ]
    )


def transform_player_stats(
    league: League,
    season: int,
    snapshot_date: dt.date,
    ingested_at: dt.datetime,
    free_agents: list = (),
) -> pd.DataFrame:
    """Per-game stat lines for every rostered player and every free agent passed in
    (the free agents' lines are what the waiver analyzer compares against)."""
    rows = []
    seen = set()
    players = [p for team in league.teams for p in team.roster] + list(free_agents)
    for player in players:
        if player.playerId in seen:
            continue  # a player can't be both, but never write a duplicate key
        seen.add(player.playerId)
        for suffix, stat_window in WINDOW_SUFFIXES.items():
            window_data = player.stats.get(f"{season}{suffix}")
            if not window_data or "avg" not in window_data:
                continue  # no games played in this window yet
            avg = window_data["avg"]
            row = {
                "snapshot_date": snapshot_date,
                "season": season,
                "player_id": player.playerId,
                "stat_window": stat_window,
                "ingested_at": ingested_at,
            }
            for espn_key, column in CATEGORY_COLUMNS.items():
                row[column] = avg.get(espn_key)
            rows.append(row)
    return pd.DataFrame(rows)


# ESPN's activity message types (espn_api.basketball.constant.ACTIVITY_MAP):
# 178 FA added, 180 waiver added, 179/181/239 dropped, 244 traded, 188 lineup move.
ACTIVITY_TYPES = [178, 180, 179, 239, 181, 244, 188]


def fetch_activity(league: League, page_size: int = 50, max_pages: int = 100) -> list[dict]:
    """Every activity topic this season, newest first -- adds, drops, trades and
    lineup moves -- straight from ESPN's league communication feed.

    Read raw rather than through league.recent_activity(): espn_api discards the team
    on a lineup move and the player id on every action, both of which the raw
    messages carry. Pages through with an offset until a page comes back short, so a
    busy day can't push activity out of reach; max_pages caps it at 5,000."""
    topics = []
    for page in range(max_pages):
        filters = {
            "topics": {
                "filterType": {"value": ["ACTIVITY_TRANSACTIONS"]},
                "limit": page_size,
                "limitPerMessageSet": {"value": 25},
                "offset": page * page_size,
                "sortMessageDate": {"sortPriority": 1, "sortAsc": False},
                "sortFor": {"sortPriority": 2, "sortAsc": False},
                "filterIncludeMessageTypeIds": {"value": ACTIVITY_TYPES},
            }
        }
        data = league.espn_request.league_get(
            extend="/communication/",
            params={"view": "kona_league_communication"},
            headers={"x-fantasy-filter": json.dumps(filters)},
        )
        batch = data.get("topics", [])
        topics.extend(batch)
        if len(batch) < page_size:
            break
    return topics


def _activity_team(msg: dict):
    """Which team a message is about -- the same fields espn_api reads, plus "for" on
    a lineup move, which espn_api leaves blank."""
    if msg["messageTypeId"] == 244:
        return msg.get("from")
    if msg["messageTypeId"] in (239, 188):
        return msg.get("for")
    return msg.get("to")


def transform_transactions(
    topics: list[dict], season: int, ingested_at: dt.datetime, player_names: dict
) -> pd.DataFrame:
    """One row per action. player_names maps ESPN player id -> name
    (league.player_map)."""
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
            if action == "MOVED":  # lineup slots: where from, where to
                slot_from = POSITION_MAP.get(msg.get("from"), "?")
                detail = f"{slot_from} to {POSITION_MAP.get(msg.get('to'), '?')}"
            # ESPN has no stable transaction id -- txn_id is a deterministic hash of
            # what's available, which is also the natural key MERGE idempotency relies
            # on. Same recipe as before reading the feed raw, so old rows still match.
            txn_key = f"{topic['date']}:{team_id}:{action}:{player_name}"
            rows.append(
                {
                    "txn_id": hashlib.sha256(txn_key.encode()).hexdigest()[:32],
                    "txn_date": txn_date,
                    "season": season,
                    "team_id": team_id,
                    "action": action,
                    "player_id": player_id,
                    "player_name": player_name,
                    "detail": detail,
                    "ingested_at": ingested_at,
                }
            )
    return pd.DataFrame(rows)


GAMES_PLAYED_STAT = "42"  # ESPN's stat id for games played


def _games_played(record: dict, season: int):
    for stat in record.get("stats", []):
        if (
            stat.get("seasonId") == season
            and stat.get("statSourceId") == 0
            and stat.get("statSplitTypeId") == 0
        ):
            return stat.get("stats", {}).get(GAMES_PLAYED_STAT)
    return None


def transform_player_seasons(
    records_by_season: dict[int, list[dict]], season: int, ingested_at: dt.datetime
) -> pd.DataFrame:
    """Games played in each past season (records_by_season: history season ->
    fetch_player_info records). A player with no line that season (not in the NBA
    yet) gets no row, so averages only count seasons he was around for."""
    rows = []
    for history_season, records in records_by_season.items():
        for record in records:
            games = _games_played(record, history_season)
            if games is None:
                continue
            rows.append(
                {
                    "season": season,
                    "player_id": record["id"],
                    "history_season": history_season,
                    "games_played": float(games),
                    "ingested_at": ingested_at,
                }
            )
    return pd.DataFrame(rows)


def transform_player_details(
    records: list[dict], season: int, snapshot_date: dt.date, ingested_at: dt.datetime
) -> pd.DataFrame:
    """Everything ESPN says about a player's health, plus its written outlook:
    injured flag, injury status, expected return date (often empty), and the
    season outlook paragraph, which is where injury context usually lives."""
    rows = []
    for record in records:
        returns = record.get("expectedReturnDate")  # [year, month, day] when present
        rows.append(
            {
                "snapshot_date": snapshot_date,
                "season": season,
                "player_id": record["id"],
                "injured": record.get("injured"),
                "injury_status": record.get("injuryStatus"),
                "expected_return_date": dt.date(*returns[:3]) if returns else None,
                "season_outlook": record.get("seasonOutlook") or None,
                "ingested_at": ingested_at,
            }
        )
    return pd.DataFrame(rows)
