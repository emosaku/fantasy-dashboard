"""Tests for ingest/transform.py's riskiest logic: unpacking box_scores()'s
home/away structure, selecting a player's populated stat window, and flattening
recent_activity()'s bundled action lists. Fakes mimic only the real espn-api
attributes transform.py reads (see notebooks/01_explore_espn_api.py)."""

import datetime as dt
from types import SimpleNamespace

import pandas as pd
from ingest.transform import (
    transform_matchup_categories,
    transform_player_stats,
    transform_rosters,
    transform_teams,
    transform_transactions,
)

INGESTED_AT = dt.datetime(2026, 10, 4, tzinfo=dt.UTC)
SNAPSHOT_DATE = INGESTED_AT.date()


def make_team(team_id, roster=None):
    return SimpleNamespace(
        team_id=team_id,
        team_name=f"Team {team_id}",
        owners=[{"displayName": f"Owner{team_id}"}],
        wins=1,
        losses=0,
        ties=0,
        standing=team_id,
        roster=roster or [],
    )


def make_player(player_id, stats):
    return SimpleNamespace(
        playerId=player_id,
        name=f"Player {player_id}",
        position="PG",
        lineupSlot="PG",
        injuryStatus="ACTIVE",
        stats=stats,
    )


def test_transform_teams_pulls_owner_from_nested_dict():
    league = SimpleNamespace(teams=[make_team(1), make_team(2)])

    df = transform_teams(league, season=2027, snapshot_date=SNAPSHOT_DATE, ingested_at=INGESTED_AT)

    assert len(df) == 2
    assert df.iloc[0]["owner"] == "Owner1"
    assert df.iloc[0]["team_id"] == 1


def test_transform_matchup_categories_unpacks_both_sides_of_each_box_score():
    home = make_team(1)
    away = make_team(2)
    box = SimpleNamespace(
        home_team=home,
        away_team=away,
        home_stats={"PTS": {"value": 100.0, "result": "W"}, "FGA": {"value": 50.0, "result": None}},
        away_stats={"PTS": {"value": 90.0, "result": "L"}, "FGA": {"value": 45.0, "result": None}},
    )
    league = SimpleNamespace(box_scores=lambda matchup_period: [box])

    df = transform_matchup_categories(
        league, season=2027, current_matchup_period=1, ingested_at=INGESTED_AT
    )

    # 2 categories x 2 sides = 4 rows, not 2 -- the bug this guards against is only
    # ever reading one side of home_stats/away_stats.
    assert len(df) == 4
    home_pts = df[(df.team_id == 1) & (df.category == "PTS")].iloc[0]
    assert home_pts.opponent_id == 2
    assert home_pts.value == 100.0
    # FGA is an attempt-only category -- result is missing, not a fabricated W/L/T.
    assert pd.isna(df[(df.team_id == 1) & (df.category == "FGA")].iloc[0]["result"])


def test_transform_matchup_categories_skips_bye_week():
    bye = SimpleNamespace(home_team=make_team(1), away_team=None, home_stats={}, away_stats={})
    league = SimpleNamespace(box_scores=lambda matchup_period: [bye])

    df = transform_matchup_categories(
        league, season=2027, current_matchup_period=1, ingested_at=INGESTED_AT
    )

    assert df.empty


def test_transform_player_stats_only_includes_populated_windows():
    # Mirrors real preseason data: only "_projected" has an "avg" sub-dict; last_7/
    # last_15/last_30/total exist but are still all zero with no "avg" key yet.
    player = make_player(
        99,
        stats={
            "2027_last_7": {"applied_total": 0, "applied_avg": 0},
            "2027_projected": {
                "applied_total": 0,
                "applied_avg": 0,
                "avg": {"PTS": 20.0, "REB": 5.0, "TO": 2.0, "3PA": 6.0},
            },
        },
    )
    league = SimpleNamespace(teams=[make_team(1, roster=[player])])

    df = transform_player_stats(
        league, season=2027, snapshot_date=SNAPSHOT_DATE, ingested_at=INGESTED_AT
    )

    assert len(df) == 1
    row = df.iloc[0]
    assert row["stat_window"] == "projected"
    assert row["pts"] == 20.0
    assert row["turnovers"] == 2.0
    assert row["fg3a"] == 6.0
    assert pd.isna(row["fg3m"])  # category absent from this player's avg dict


def test_transform_rosters_pulls_one_row_per_player():
    players = [make_player(1, stats={}), make_player(2, stats={})]
    league = SimpleNamespace(teams=[make_team(1, roster=players)])

    df = transform_rosters(
        league, season=2027, snapshot_date=SNAPSHOT_DATE, ingested_at=INGESTED_AT
    )

    assert len(df) == 2
    assert set(df["player_id"]) == {1, 2}


def test_transform_transactions_flattens_bundled_actions_and_hashes_consistently():
    team = make_team(1)
    activity = SimpleNamespace(
        date=1_700_000_000_000,
        actions=[(team, "TRADED", "Player A", ""), (team, "TRADED", "Player B", "")],
    )
    league = SimpleNamespace(recent_activity=lambda size: [activity])

    df = transform_transactions(league, season=2027, size=10, ingested_at=INGESTED_AT)

    assert len(df) == 2
    assert pd.isna(df.iloc[0]["player_id"])
    assert df.iloc[0]["txn_id"] != df.iloc[1]["txn_id"]

    # Re-running with the same input must produce the same txn_id -- that's what
    # makes the MERGE idempotent.
    df_again = transform_transactions(league, season=2027, size=10, ingested_at=INGESTED_AT)
    assert df.iloc[0]["txn_id"] == df_again.iloc[0]["txn_id"]
