"""Tests for ingest/transform.py's riskiest logic: unpacking box_scores()'s
home/away structure, the long per-game stat rows, flattening activity's bundled
actions, and past-season games played. Every row must carry league_id and season.
Fakes mimic only the espn-api attributes transform.py reads."""

import datetime as dt
import hashlib
from types import SimpleNamespace

import pandas as pd
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
    week_of,
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


# --- Points leagues -----------------------------------------------------------------

SCORING = [{"stat": "PTS", "points": 1.0}, {"stat": "FGA", "points": -1.0},
           {"stat": "REB", "points": 1.0}]  # fmt: skip


def test_player_points_prefer_espns_numbers_and_keep_ours_beside_them():
    espn = {"applied_avg": 18.0, "applied_total": 180.0,
            "avg": {"PTS": 20.0, "FGA": 12.0, "REB": 8.0}, "total": {"GP": 10.0}}  # fmt: skip
    preseason = {"applied_avg": 0, "applied_total": 0, "avg": {"PTS": 10.0, "FGA": 8.0}}
    player = make_player(7, {f"{SEASON}_total": espn, f"{SEASON}_projected": preseason})
    df = transform_player_points([player, player], SCORING, LEAGUE, SEASON, AT)
    rows = df.set_index("stat_window")
    assert len(df) == 2  # a repeated player isn't loaded twice
    assert rows.at["season", "fp_per_game"] == 18.0 and rows.at["season", "source"] == "espn"
    assert rows.at["season", "computed_per_game"] == 16.0 and rows.at["season", "games"] == 10
    # ESPN sent 0: our stat x points is used instead.
    assert rows.at["projected", "fp_per_game"] == 2.0
    assert rows.at["projected", "source"] == "computed"
    off = points_mismatches(df)
    assert list(off["stat_window"]) == ["season"]  # 18 vs 16: more than 0.1 apart


def test_lineup_slots_leave_out_bench_and_ir():
    raw = {"rosterSettings": {"lineupSlotCounts": {"0": 1, "5": 1, "11": 3, "12": 3, "13": 1,
                                                   "7": 0}}}  # fmt: skip
    assert lineup_slots(raw) == {"PG": 1, "G": 1, "UT": 3}
    assert bench_slots(raw) == 3


def test_matchup_scores_keep_both_sides_future_weeks_and_live_points():
    schedule = [
        {"matchupPeriodId": 1, "winner": "HOME", "playoffTierType": "NONE",
         "home": {"teamId": 1, "totalPoints": 510.5}, "away": {"teamId": 2, "totalPoints": 480.0}},
        {"matchupPeriodId": 2, "winner": "UNDECIDED", "playoffTierType": "NONE",
         "home": {"teamId": 2, "totalPoints": 0, "totalPointsLive": 120.0},
         "away": {"teamId": 1, "totalPoints": 0, "totalPointsLive": 99.0}},
        {"matchupPeriodId": 3, "winner": "UNDECIDED", "playoffTierType": "WINNERS_BRACKET",
         "home": {"teamId": 1, "totalPoints": 0}, "away": {"teamId": 2, "totalPoints": 0}},
        {"matchupPeriodId": 3, "home": {"teamId": 3}},  # a bye
    ]  # fmt: skip
    df = transform_matchup_scores(schedule, 2, LEAGUE, SEASON, AT)
    assert len(df) == 6
    week2 = df.loc[(df["matchup_period"] == 2) & (df["team_id"] == 1)].iloc[0]
    assert (week2["points"], week2["opponent_points"], week2["is_home"]) == (99.0, 120.0, False)
    assert df.loc[df["matchup_period"] == 3, "is_playoff"].all()
    assert not df.loc[df["matchup_period"] == 1, "is_playoff"].any()


def test_pro_schedule_maps_days_to_matchup_weeks():
    def at(day, hour=0):  # ESPN dates are tip-off times in UTC (7:30 pm ET = 23:30 UTC)
        return int(dt.datetime(2026, 10, day, hour, 30, tzinfo=dt.UTC).timestamp() * 1000)

    # Opening night Tue Oct 20; Sun Oct 25 ends week 1; Mon Oct 26 starts week 2.
    pro = {
        2: {"1": [{"date": at(20, 23)}], "6": [{"date": at(26, 2)}], "7": [{"date": at(26, 23)}]},
        0: {"1": [{"date": at(20, 23)}]},  # the "free agent" pseudo-team
    }
    df = transform_pro_schedule(pro, {"1": [1], "2": [2]}, {}, LEAGUE, SEASON, AT)
    rows = df.set_index("scoring_period")
    assert list(rows["pro_team"].unique()) == ["BOS"]
    # 2 am UTC on Oct 26 is a 10 pm ET Oct 25 tip: still week 1.
    assert rows.at[6, "game_date"] == dt.date(2026, 10, 25)
    assert list(rows["matchup_period"]) == [1, 1, 2]
    # Once ESPN has scored a week, its own days win.
    exact = transform_pro_schedule(pro, {"1": [1], "2": [2]}, {2: ["6", "7"]}, LEAGUE, SEASON, AT)
    assert list(exact.set_index("scoring_period")["matchup_period"]) == [1, 2, 2]


def test_week_of_counts_monday_weeks_from_opening_night():
    opening = dt.date(2026, 10, 20)  # a Tuesday
    assert week_of(opening, opening) == 1
    assert week_of(dt.date(2026, 10, 25), opening) == 1
    assert week_of(dt.date(2026, 10, 26), opening) == 2


def test_rosters_and_free_agents_carry_team_and_eligible_slots():
    player = make_player(1, {})
    player.proTeam, player.eligibleSlots = "LAL", ["PG", "G", "UT", "BE", "IR"]
    league = SimpleNamespace(teams=[make_team(1, roster=[player])])
    row = transform_rosters(league, LEAGUE, SEASON, AT).iloc[0]
    assert (row["pro_team"], row["eligible_slots"]) == ("LAL", "PG,G,UT")
    assert (
        transform_free_agents([player], LEAGUE, SEASON, AT).iloc[0]["eligible_slots"] == "PG,G,UT"
    )


# --- Draft tool --------------------------------------------------------------------------


def pool_record(pid, applied=None, gp=70.0, adp=5.0):
    return {
        "id": pid,
        "fullName": f"Player {pid}",
        "proTeamId": 2,
        "defaultPositionId": 5,
        "eligibleSlots": [4, 9, 10, 11, 12, 13],  # C, PF/C, F/C, UT, BE, IR
        "injuryStatus": "ACTIVE",
        "ownership": {"averageDraftPosition": adp, "auctionValueAverage": 30.0,
                      "percentOwned": 99.0},
        "draftRanksByRankType": {"STANDARD": {"rank": 4}, "ROTO": {"rank": 9}},
        "stats": [
            {"seasonId": SEASON, "statSourceId": 1, "statSplitTypeId": 0, "appliedAverage": applied,
             "averageStats": {"0": 20.0, "14": 15.0, "6": 10.0, "42": 1.0}, "stats": {"42": gp}},
            {"seasonId": SEASON - 1, "statSourceId": 0, "statSplitTypeId": 0,
             "stats": {"42": 61.0}},
        ],
    }  # fmt: skip


def test_draft_pool_rows_carry_adp_ranks_and_projections():
    records = [pool_record(1), pool_record(2, applied=33.5)]
    df = transform_draft_pool(records, SEASON, SCORING, {1: 58.0}, LEAGUE, AT).set_index(
        "player_id"
    )
    one = df.loc[1]
    assert (one["pro_team"], one["position"], one["eligible_slots"]) == (
        "BOS",
        "C",
        "C,PF/C,F/C,UT",
    )
    assert (one["adp"], one["rank"], one["rank_roto"]) == (5.0, 4, 9)
    assert one["proj_fpg"] == 20 - 15 + 10  # our stat x points: ESPN sent no applied average
    assert df.loc[2, "proj_fpg"] == 33.5  # ESPN's own, when it has one
    assert (one["proj_games"], one["last_season_games"], one["history_games"]) == (70, 61, 58)
    assert pd.isna(df.loc[2, "history_games"])
    no_points = transform_draft_pool(records[:1], SEASON, [], {}, LEAGUE, AT).iloc[0]
    assert pd.isna(no_points["proj_fpg"])  # a categories league has no point values


def test_draft_pool_stats_keep_the_projected_line():
    df = transform_draft_pool_stats([pool_record(1)], SEASON, ["PTS", "REB", "AST"], LEAGUE, AT)
    assert dict(zip(df["stat"], df["value"], strict=True)) == {"PTS": 20.0, "REB": 10.0}


def test_draft_settings_count_every_roster_spot_but_ir():
    raw = {
        "draftSettings": {"type": "SNAKE", "pickOrder": [3, 1, 2], "timePerSelection": 60,
                          "keeperCount": 0, "date": 1_791_337_080_000},
        "rosterSettings": {"lineupSlotCounts": {"0": 1, "11": 3, "12": 3, "13": 2}},
    }  # fmt: skip
    s = draft_settings(raw, {"drafted": False, "inProgress": True})
    assert (s["type"], s["pick_order"], s["rounds"]) == ("SNAKE", [3, 1, 2], 7)
    assert s["date"] == dt.datetime(2026, 10, 7, 1, 38, tzinfo=dt.UTC)
    assert (s["drafted"], s["in_progress"]) == (False, True)


def test_draft_picks_skip_empty_keeper_slots():
    detail = {"picks": [
        {"overallPickNumber": 1, "roundId": 1, "roundPickNumber": 1, "teamId": 6, "playerId": 9},
        {"overallPickNumber": 2, "roundId": 1, "roundPickNumber": 2, "teamId": 8, "playerId": -1},
    ]}  # fmt: skip
    df = transform_draft_picks(detail, LEAGUE, SEASON, AT)
    assert list(df["player_id"]) == [9] and not df["keeper"].any()
    assert transform_draft_picks(None, LEAGUE, SEASON, AT).empty
