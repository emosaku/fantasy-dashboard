"""Turns espn-api objects into DataFrames matching sql/ddl/*.sql exactly.

Field shapes here come from inspecting the real API (notebooks/01_explore_espn_api.py),
not from espn-api's docs -- field names shift between library versions.
"""

import datetime as dt
import hashlib

import pandas as pd
from espn_api.basketball import League

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
# project's column names.
CATEGORY_COLUMNS = {
    "PTS": "pts",
    "REB": "reb",
    "AST": "ast",
    "STL": "stl",
    "BLK": "blk",
    "3PM": "fg3m",
    "FGM": "fgm",
    "FGA": "fga",
    "FTM": "ftm",
    "FTA": "fta",
    "TO": "turnovers",
}


def transform_teams(
    league: League, season: int, snapshot_date: dt.date, ingested_at: dt.datetime
) -> pd.DataFrame:
    rows = []
    for team in league.teams:
        owners = team.owners or []
        owner = ", ".join(o.get("displayName", "") for o in owners) or None
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
                    "ingested_at": ingested_at,
                }
            )
    return pd.DataFrame(rows)


def transform_player_stats(
    league: League, season: int, snapshot_date: dt.date, ingested_at: dt.datetime
) -> pd.DataFrame:
    rows = []
    for team in league.teams:
        for player in team.roster:
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


def transform_transactions(
    league: League, season: int, size: int, ingested_at: dt.datetime
) -> pd.DataFrame:
    rows = []
    for activity in league.recent_activity(size=size):
        txn_date = dt.datetime.fromtimestamp(activity.date / 1000, tz=dt.UTC)
        for team, action, player_name, _ in activity.actions:
            # recent_activity()'s tuples give a player name, not an id, and ESPN has
            # no stable transaction id -- txn_id is a deterministic hash of what's
            # available, which also makes it the natural key MERGE idempotency relies on.
            txn_key = f"{activity.date}:{team.team_id}:{action}:{player_name}"
            txn_id = hashlib.sha256(txn_key.encode()).hexdigest()[:32]
            rows.append(
                {
                    "txn_id": txn_id,
                    "txn_date": txn_date,
                    "season": season,
                    "team_id": team.team_id,
                    "action": action,
                    "player_id": None,
                    "player_name": player_name,
                    "ingested_at": ingested_at,
                }
            )
    return pd.DataFrame(rows)
