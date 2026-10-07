"""Tests for ingest/transform.py's riskiest logic: unpacking box_scores()'s
home/away structure, the long per-game stat rows, flattening activity's bundled
actions, and past-season games played. Every row must carry league_id and season.
Fakes mimic only the espn-api attributes transform.py reads."""

import datetime as dt
import hashlib
from types import SimpleNamespace

import pandas as pd
from ingest.transform import (
    transform_free_agents,
    transform_league_categories,
    transform_league_settings,
    transform_matchup_categories,
    transform_player_details,
    transform_player_seasons,
    transform_player_stats,
    transform_rosters,
    transform_teams,
    transform_transactions,
)

AT = dt.datetime(2026, 10, 4, tzinfo=dt.UTC)
LEAGUE, SEASON = 555, 2027


def make_team(team_id, roster=None):
    return SimpleNamespace(
        team_id=team_id,
        team_name=f"Team {team_id} ",
        owners=[{"displayName": f"ESPNFAN{team_id}", "firstName": "Pat ", "lastName": "Lee"}],
        wins=1,
        losses=0,
        ties=0,
        standing=team_id,
        roster=roster or [],
    )


def make_player(player_id, stats=None):
    return SimpleNamespace(
        playerId=player_id,
        name=f"Player {player_id}",
        position="PG",
        lineupSlot="PG",
        injuryStatus="ACTIVE",
        stats=stats or {},
    )


def test_league_settings_reads_format_and_season_length():
    league = SimpleNamespace(
        teams=[make_team(1), make_team(2)],
        currentMatchupPeriod=5,
        settings=SimpleNamespace(reg_season_count=16),
    )
    raw = {
        "name": "Hoops",
        "scoringSettings": {"scoringType": "H2H_EACH_CATEGORY"},
        "scheduleSettings": {"matchupPeriodCount": 18, "playoffTeamCount": 6},
    }
    row = transform_league_settings(league, raw, LEAGUE, SEASON, AT).iloc[0]
    assert (row["league_id"], row["season"], row["league_name"]) == (LEAGUE, SEASON, "Hoops")
    assert (row["scoring_type"], row["team_count"]) == ("H2H_EACH_CATEGORY", 2)
    assert (row["current_matchup_period"], row["reg_season_matchup_periods"]) == (5, 18)


def test_league_settings_stores_espns_each_category_as_each_category():
    league = SimpleNamespace(
        teams=[make_team(1)], currentMatchupPeriod=1, settings=SimpleNamespace(reg_season_count=16)
    )
    raw = {"scoringSettings": {"scoringType": "H2H_CATEGORY"}, "scheduleSettings": {}}
    row = transform_league_settings(league, raw, LEAGUE, SEASON, AT).iloc[0]
    assert row["scoring_type"] == "H2H_EACH_CATEGORY"


def test_league_categories_rows_carry_the_league():
    cats = [{"category": "TO", "kind": "count", "num_stat": "TO", "den_stat": None,
             "lower_is_better": True, "display_order": 0}]  # fmt: skip
    row = transform_league_categories(cats, LEAGUE, SEASON, AT).iloc[0]
    assert (row["league_id"], row["category"], row["lower_is_better"]) == (LEAGUE, "TO", True)


def test_teams_use_real_names_and_fall_back_to_username():
    nameless = make_team(2)
    nameless.owners = [{"displayName": "hoopsfan", "firstName": "", "lastName": None}]
    df = transform_teams(SimpleNamespace(teams=[make_team(1), nameless]), LEAGUE, SEASON, AT)
    assert list(df["owner"]) == ["Pat Lee", "hoopsfan"]
    assert df.iloc[0]["team_name"] == "Team 1"  # stray space stripped
    assert (df["league_id"] == LEAGUE).all()


def test_matchup_categories_unpack_both_sides_of_each_box_score():
    box = SimpleNamespace(
        home_team=make_team(1),
        away_team=make_team(2),
        home_stats={"PTS": {"value": 100.0, "result": "W"}, "FGA": {"value": 50.0}},
        away_stats={"PTS": {"value": 90.0, "result": "L"}, "FGA": {"value": 45.0}},
    )
    league = SimpleNamespace(box_scores=lambda matchup_period: [box])

    df = transform_matchup_categories(league, [3], LEAGUE, SEASON, AT)

    # 2 categories x 2 sides = 4 rows, not 2.
    assert len(df) == 4
    home_pts = df[(df.team_id == 1) & (df.category == "PTS")].iloc[0]
    assert (home_pts.opponent_id, home_pts.value, home_pts.matchup_period) == (2, 100.0, 3)
    assert pd.isna(df[(df.team_id == 1) & (df.category == "FGA")].iloc[0]["result"])


def test_matchup_categories_skip_bye_weeks():
    bye = SimpleNamespace(home_team=make_team(1), away_team=None, home_stats={}, away_stats={})
    league = SimpleNamespace(box_scores=lambda matchup_period: [bye])
    assert transform_matchup_categories(league, [1], LEAGUE, SEASON, AT).empty


def test_player_stats_are_long_and_skip_unfilled_windows():
    # Preseason: only "_projected" has an "avg" dict yet.
    player = make_player(
        99,
        {
            f"{SEASON}_last_7": {"applied_total": 0},
            f"{SEASON}_projected": {"avg": {"PTS": 20.0, "TO": 2.0, "3PA": 6.0, "XYZ": 1.0}},
        },
    )
    df = transform_player_stats([player, player], LEAGUE, SEASON, AT)  # repeat ignored
    assert set(df["stat_window"]) == {"projected"}
    assert dict(zip(df["stat"], df["value"], strict=True)) == {"3PA": 6.0, "PTS": 20.0, "TO": 2.0}


def test_rosters_and_free_agents():
    hurt = make_player(1)
    hurt.expected_return_date = dt.date(2026, 11, 20)
    df = transform_rosters(
        SimpleNamespace(teams=[make_team(4, [hurt, make_player(2)])]), LEAGUE, SEASON, AT
    )
    assert list(df["player_id"]) == [1, 2] and (df["team_id"] == 4).all()
    assert df.iloc[0]["expected_return_date"] == dt.date(2026, 11, 20)
    assert pd.isna(df.iloc[1]["expected_return_date"])

    fa = make_player(7)
    fa.proTeam, fa.injuryStatus = "NOP", "OUT"
    row = transform_free_agents([fa], LEAGUE, SEASON, AT).iloc[0]
    assert (row["player_id"], row["pro_team"], row["injury_status"]) == (7, "NOP", "OUT")


def msg(type_id, target, **fields):
    return {"messageTypeId": type_id, "targetId": target, **fields}


NAMES = {101: "Player A", 102: "Player B", 103: "Player C"}


def test_transactions_flatten_bundled_actions_with_stable_ids():
    legs = [msg(244, 101, **{"from": 1, "to": 2}), msg(244, 102, **{"from": 2, "to": 1})]
    trade = {"date": 1_700_000_000_000, "messages": legs}

    df = transform_transactions([trade], NAMES, LEAGUE, SEASON, AT)

    assert list(df["player_id"]) == [101, 102]
    assert list(df["team_id"]) == [1, 2]  # a trade is filed under the team sending
    assert df.iloc[0]["txn_id"] != df.iloc[1]["txn_id"]
    again = transform_transactions([trade], NAMES, LEAGUE, SEASON, AT)
    assert list(df["txn_id"]) == list(again["txn_id"])


def test_txn_id_includes_the_league():
    add = {"date": 1_700_000_000_000, "messages": [msg(178, 101, to=4)]}
    df = transform_transactions([add], NAMES, LEAGUE, SEASON, AT)
    key = f"{LEAGUE}:1700000000000:4:FA ADDED:Player A".encode()
    assert df.iloc[0]["txn_id"] == hashlib.sha256(key).hexdigest()[:32]
    other = transform_transactions([add], NAMES, LEAGUE + 1, SEASON, AT)
    assert other.iloc[0]["txn_id"] != df.iloc[0]["txn_id"]


def test_lineup_moves_keep_their_team_and_slots():
    move = {
        "date": 1_700_000_000_000,
        "messages": [msg(188, 103, **{"for": 3, "from": 12, "to": 11})],
    }
    row = transform_transactions([move], NAMES, LEAGUE, SEASON, AT).iloc[0]
    assert (row["action"], row["team_id"], row["player_name"]) == ("MOVED", 3, "Player C")
    assert row["detail"] == "BE to UT"


def season_total(season, games):
    return {"seasonId": season, "statSourceId": 0, "statSplitTypeId": 0, "stats": {"42": games}}


def test_player_seasons_record_null_for_players_without_a_line():
    butler = {"id": 6430, "stats": [season_total(2026, 38.0)]}
    projected = {"id": 7, "stats": [{"seasonId": 2026, "statSourceId": 1, "statSplitTypeId": 0,
                                     "stats": {"42": 70.0}}]}  # fmt: skip
    df = transform_player_seasons({2026: [butler, projected]}, [6430, 7, 5000], AT)
    got = dict(zip(df["player_id"], df["games_played"], strict=True))
    assert got[6430] == 38.0
    assert pd.isna(got[7]) and pd.isna(got[5000])  # a projection isn't a season played
    assert (df["history_season"] == 2026).all()


def test_player_details_keep_injury_fields_and_outlook():
    records = [
        {"id": 1, "injured": True, "injuryStatus": "OUT", "expectedReturnDate": [2026, 11, 20],
         "seasonOutlook": "Missed time last year with a knee issue."},
        {"id": 2, "injured": False, "injuryStatus": "ACTIVE", "seasonOutlook": ""},
    ]  # fmt: skip
    df = transform_player_details(records, LEAGUE, SEASON, AT).set_index("player_id")
    assert df.loc[1, "expected_return_date"] == dt.date(2026, 11, 20)
    assert pd.isna(df.loc[2, "expected_return_date"])
    assert pd.isna(df.loc[2, "season_outlook"])
