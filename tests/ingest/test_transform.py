"""Tests for ingest/transform.py's riskiest logic: unpacking box_scores()'s
home/away structure, selecting a player's populated stat window, and flattening
recent_activity()'s bundled action lists. Fakes mimic only the real espn-api
attributes transform.py reads (see notebooks/01_explore_espn_api.py)."""

import datetime as dt
import hashlib
import json
from types import SimpleNamespace

import pandas as pd
from ingest.transform import (
    fetch_activity,
    transform_free_agents,
    transform_league_status,
    transform_matchup_categories,
    transform_player_details,
    transform_player_seasons,
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
        owners=[{"displayName": f"ESPNFAN{team_id}", "firstName": "Pat ", "lastName": "Lee"}],
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


def test_transform_league_status_reads_current_week_and_season_length():
    league = SimpleNamespace(
        currentMatchupPeriod=5,
        settings=SimpleNamespace(reg_season_count=16, playoff_team_count=8),
    )

    df = transform_league_status(
        league, season=2027, snapshot_date=SNAPSHOT_DATE, ingested_at=INGESTED_AT
    )

    assert len(df) == 1
    row = df.iloc[0]
    assert row["current_matchup_period"] == 5
    assert row["reg_season_matchup_periods"] == 16
    assert row["playoff_team_count"] == 8
    assert pd.isna(row["trade_deadline"])  # no deadline in these settings
    assert pd.isna(row["trade_review_hours"])


def test_transform_league_status_reads_the_trade_deadline_and_review_period():
    deadline_ms = 1_772_000_000_000
    league = SimpleNamespace(
        currentMatchupPeriod=5,
        settings=SimpleNamespace(
            reg_season_count=16, trade_deadline=deadline_ms, trade_revision_hours=48
        ),
    )
    row = transform_league_status(
        league, season=2027, snapshot_date=SNAPSHOT_DATE, ingested_at=INGESTED_AT
    ).iloc[0]
    assert row["trade_deadline"] == pd.Timestamp(deadline_ms, unit="ms", tz="UTC")
    assert row["trade_review_hours"] == 48


def test_transform_teams_falls_back_to_username_without_a_name():
    team = make_team(1)
    team.owners = [{"displayName": "hoopsfan", "firstName": "", "lastName": None}]
    league = SimpleNamespace(teams=[team])

    df = transform_teams(league, season=2027, snapshot_date=SNAPSHOT_DATE, ingested_at=INGESTED_AT)

    assert df.iloc[0]["owner"] == "hoopsfan"


def test_transform_teams_pulls_owner_from_nested_dict():
    league = SimpleNamespace(teams=[make_team(1), make_team(2)])

    df = transform_teams(league, season=2027, snapshot_date=SNAPSHOT_DATE, ingested_at=INGESTED_AT)

    assert len(df) == 2
    assert df.iloc[0]["owner"] == "Pat Lee"  # real name, stray space stripped
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


def msg(type_id, target, **fields):
    return {"messageTypeId": type_id, "targetId": target, **fields}


NAMES = {101: "Player A", 102: "Player B", 103: "Player C"}


def test_transform_transactions_flattens_bundled_actions_and_hashes_consistently():
    legs = [msg(244, 101, **{"from": 1, "to": 2}), msg(244, 102, **{"from": 2, "to": 1})]
    trade = {"date": 1_700_000_000_000, "messages": legs}

    df = transform_transactions([trade], 2027, INGESTED_AT, NAMES)

    assert len(df) == 2
    assert list(df["player_id"]) == [101, 102]  # ids now come through
    assert list(df["team_id"]) == [1, 2]  # a trade is filed under the team sending
    assert df.iloc[0]["txn_id"] != df.iloc[1]["txn_id"]
    # Re-running with the same input must produce the same txn_id -- that's what
    # makes the MERGE idempotent.
    again = transform_transactions([trade], 2027, INGESTED_AT, NAMES)
    assert list(df["txn_id"]) == list(again["txn_id"])


def test_txn_id_recipe_is_unchanged_so_old_rows_still_match():
    add = {"date": 1_700_000_000_000, "messages": [msg(178, 101, to=4)]}
    df = transform_transactions([add], 2027, INGESTED_AT, NAMES)
    expected = hashlib.sha256(b"1700000000000:4:FA ADDED:Player A").hexdigest()[:32]
    assert df.iloc[0]["txn_id"] == expected


def test_lineup_moves_keep_their_team_and_slots():
    move = {
        "date": 1_700_000_000_000,
        "messages": [msg(188, 103, **{"for": 3, "from": 12, "to": 11})],
    }

    row = transform_transactions([move], 2027, INGESTED_AT, NAMES).iloc[0]

    assert (row["action"], row["team_id"], row["player_name"]) == ("MOVED", 3, "Player C")
    assert row["detail"] == "BE to UT"


def test_fetch_activity_pages_through_the_whole_season():
    history = [{"date": i, "messages": []} for i in range(23)]
    offsets = []

    def league_get(extend, params, headers):
        topics = json.loads(headers["x-fantasy-filter"])["topics"]
        offsets.append(topics["offset"])
        assert 188 in topics["filterIncludeMessageTypeIds"]["value"]  # moves included
        page = history[topics["offset"] : topics["offset"] + topics["limit"]]
        return {"topics": page}

    league = SimpleNamespace(espn_request=SimpleNamespace(league_get=league_get))
    assert len(fetch_activity(league, page_size=10)) == 23  # all of it, not one page
    assert offsets == [0, 10, 20]  # stops after the short page


def test_transform_free_agents_one_row_per_player():
    fa = make_player(7, stats={})
    fa.proTeam = "NOP"
    fa.injuryStatus = "OUT"

    df = transform_free_agents(
        [fa], season=2027, snapshot_date=SNAPSHOT_DATE, ingested_at=INGESTED_AT
    )

    assert len(df) == 1
    row = df.iloc[0]
    assert (row["player_id"], row["pro_team"], row["injury_status"]) == (7, "NOP", "OUT")


def test_transform_player_stats_includes_free_agents_and_games_played():
    projected = {"avg": {"PTS": 10.0, "GP": 66.0}}
    rostered = make_player(1, stats={"2027_projected": projected})
    free_agent = make_player(2, stats={"2027_projected": projected})
    league = SimpleNamespace(teams=[make_team(1, roster=[rostered])])

    df = transform_player_stats(
        league,
        season=2027,
        snapshot_date=SNAPSHOT_DATE,
        ingested_at=INGESTED_AT,
        free_agents=[free_agent, rostered],  # a repeat must not duplicate the key
    )

    assert sorted(df["player_id"]) == [1, 2]
    assert (df["gp"] == 66.0).all()


def test_transform_rosters_keeps_espn_return_date():
    hurt = make_player(1, stats={})
    hurt.expected_return_date = dt.date(2026, 11, 20)
    league = SimpleNamespace(teams=[make_team(1, roster=[hurt, make_player(2, stats={})])])

    df = transform_rosters(
        league, season=2027, snapshot_date=SNAPSHOT_DATE, ingested_at=INGESTED_AT
    )

    assert df.iloc[0]["expected_return_date"] == dt.date(2026, 11, 20)
    assert pd.isna(df.iloc[1]["expected_return_date"])  # no estimate from ESPN


def season_total(season, games):
    return {"seasonId": season, "statSourceId": 0, "statSplitTypeId": 0, "stats": {"42": games}}


def test_player_seasons_reads_games_played_per_past_season():
    butler = {"id": 6430, "stats": [season_total(2026, 38.0)]}
    rookie = {"id": 5000, "stats": []}  # no NBA line that season
    projected = {"id": 7, "stats": [{"seasonId": 2026, "statSourceId": 1, "statSplitTypeId": 0,
                                     "stats": {"42": 70.0}}]}  # fmt: skip

    df = transform_player_seasons(
        {
            2025: [{"id": 6430, "stats": [season_total(2025, 55.0)]}],
            2026: [butler, rookie, projected],
        },
        season=2027,
        ingested_at=INGESTED_AT,
    )

    assert sorted(zip(df["history_season"], df["games_played"])) == [(2025, 55.0), (2026, 38.0)]
    assert set(df["player_id"]) == {6430}  # no rows for missing seasons or projections


def test_player_details_keeps_injury_fields_and_outlook():
    records = [
        {"id": 1, "injured": True, "injuryStatus": "OUT", "expectedReturnDate": [2026, 11, 20],
         "seasonOutlook": "Missed time last year with a knee issue."},
        {"id": 2, "injured": False, "injuryStatus": "ACTIVE", "seasonOutlook": ""},
    ]  # fmt: skip

    df = transform_player_details(records, 2027, SNAPSHOT_DATE, INGESTED_AT).set_index("player_id")

    assert df.loc[1, "expected_return_date"] == dt.date(2026, 11, 20)
    assert df.loc[1, "injury_status"] == "OUT"
    assert pd.isna(df.loc[2, "expected_return_date"])
    assert pd.isna(df.loc[2, "season_outlook"])  # empty text stored as missing
