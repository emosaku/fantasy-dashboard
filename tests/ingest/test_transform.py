"""Tests for ingest/transform.py's riskiest logic: unpacking box_scores()'s
home/away structure, the long per-game stat rows, flattening activity's bundled
actions, and our windows, points and injuries in place of ESPN's. Every row must
carry league_id and season. Fakes mimic only the espn-api attributes transform.py reads."""

import datetime as dt
import hashlib
from types import SimpleNamespace

import pandas as pd
from ingest.transform import (
    apply_injuries,
    bench_slots,
    lineup_slots,
    points_mismatches,
    transform_free_agents,
    transform_league_categories,
    transform_league_settings,
    transform_matchup_categories,
    transform_matchup_scores,
    transform_player_details,
    transform_player_points,
    transform_pro_schedule,
    transform_projected_points,
    transform_projected_stats,
    transform_rosters,
    transform_teams,
    transform_transactions,
    transform_window_points,
    transform_window_stats,
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


def test_player_details_keep_injury_fields_but_not_espns_outlook():
    records = [
        {"id": 1, "injured": True, "injuryStatus": "OUT", "expectedReturnDate": [2026, 11, 20],
         "seasonOutlook": "Missed time last year with a knee issue."},
        {"id": 2, "injured": False, "injuryStatus": "ACTIVE", "seasonOutlook": ""},
    ]  # fmt: skip
    df = transform_player_details(records, LEAGUE, SEASON, AT).set_index("player_id")
    assert df.loc[1, "expected_return_date"] == dt.date(2026, 11, 20)
    assert pd.isna(df.loc[2, "expected_return_date"])
    assert "season_outlook" not in df


# --- Points leagues -----------------------------------------------------------------

SCORING = [{"stat": "PTS", "points": 1.0}, {"stat": "FGA", "points": -1.0},
           {"stat": "REB", "points": 1.0}]  # fmt: skip


def test_espns_points_are_read_for_the_check_only():
    espn = {"applied_avg": 18.0, "applied_total": 180.0,
            "avg": {"PTS": 20.0, "FGA": 12.0, "REB": 8.0}, "total": {"GP": 10.0}}  # fmt: skip
    preseason = {"applied_avg": 0, "applied_total": 0, "avg": {"PTS": 10.0, "FGA": 8.0}}
    player = make_player(7, {f"{SEASON}_total": espn, f"{SEASON}_projected": preseason})
    df = transform_player_points([player, player], SCORING, LEAGUE, SEASON, AT)
    assert list(df["stat_window"]) == ["season"]  # ESPN's projection is never read
    assert df.iloc[0]["fp_per_game"] == 18.0 and df.iloc[0]["source"] == "espn"


def windows():
    """run.windows' shape: long per-game lines by ESPN player id."""
    rows = [(7, "season", "PTS", 20.0), (7, "season", "FGA", 15.0), (7, "season", "REB", 6.0),
            (7, "season", "GP", 8.0), (7, "last_7", "PTS", 30.0), (7, "last_7", "GP", 3.0),
            (8, "season", "PTS", 10.0), (8, "season", "GP", 5.0)]  # fmt: skip
    return pd.DataFrame(rows, columns=["player_id", "stat_window", "stat", "value"])


def test_our_windows_fill_player_stats_for_pool_players_only():
    df = transform_window_stats(windows(), [7, 99], LEAGUE, SEASON, AT, ["PTS", "GP", "AST"])
    assert set(df["player_id"]) == {7}
    assert (df["league_id"] == LEAGUE).all() and (df["season"] == SEASON).all()
    got = {(w, s): v for w, s, v in zip(df["stat_window"], df["stat"], df["value"], strict=True)}
    assert got == {("season", "PTS"): 20.0, ("season", "GP"): 8.0,
                   ("last_7", "PTS"): 30.0, ("last_7", "GP"): 3.0}  # fmt: skip


def test_our_window_points_use_the_leagues_values():
    df = transform_window_points(windows(), [7], SCORING, LEAGUE, SEASON, AT)
    rows = df.set_index("stat_window")
    assert rows.at["season", "fp_per_game"] == 20.0 - 15.0 + 6.0
    assert rows.at["season", "fp_total"] == 11.0 * 8 and rows.at["season", "games"] == 8
    assert rows.at["last_7", "fp_per_game"] == 30.0
    assert (df["source"] == "computed").all()


def test_points_check_compares_espns_points_with_ours():
    def row(pid, window, fp, games, source="espn"):
        return {"player_id": pid, "stat_window": window, "fp_per_game": fp, "games": games,
                "source": source}  # fmt: skip

    espn = pd.DataFrame([
        row(7, "season", 11.05, 8.0),
        row(7, "last_7", 25.0, 3.0),
        row(9, "season", 2.0, 4.0, "computed"),
    ])  # fmt: skip
    ours = transform_window_points(windows(), [7, 9], SCORING, LEAGUE, SEASON, AT)
    off = points_mismatches(espn, ours)
    assert list(off["stat_window"]) == ["last_7"]  # 25 vs 30; 11.05 vs 11 is within 0.1
    assert points_mismatches(espn, ours.iloc[0:0]).empty


def test_points_check_skips_windows_where_espn_has_more_games():
    from ingest.transform import comparable

    espn = pd.DataFrame([{"player_id": 7, "stat_window": "last_7", "fp_per_game": 25.0,
                          "games": 4.0, "source": "espn"}])  # fmt: skip
    ours = transform_window_points(windows(), [7], SCORING, LEAGUE, SEASON, AT)  # 3 games
    assert comparable(espn, ours).empty
    assert points_mismatches(espn, ours).empty  # tonight's game, not a misread rule


def test_injuries_come_from_our_list_and_everyone_else_is_active():
    details = pd.DataFrame([
        {"player_id": 1, "injured": False, "injury_status": "ACTIVE", "expected_return_date": None},
        {"player_id": 2, "injured": True, "injury_status": "OUT",
         "expected_return_date": dt.date(2026, 12, 1)},
    ])  # fmt: skip
    ours = pd.DataFrame(
        {"status": ["OUT"], "return_date": [dt.date(2026, 11, 4)]}, index=pd.Index([1])
    )
    out = apply_injuries(details, ours).set_index("player_id")
    assert out.at[1, "injury_status"] == "OUT" and out.at[1, "injured"]
    assert out.at[1, "expected_return_date"] == dt.date(2026, 11, 4)
    assert out.at[2, "injury_status"] == "ACTIVE" and not out.at[2, "injured"]
    assert out.at[2, "expected_return_date"] is None  # ESPN's date isn't kept
    free_agents = pd.DataFrame([{"player_id": 2, "injury_status": "OUT"}])
    assert apply_injuries(free_agents, ours, None).iloc[0]["injury_status"] == "ACTIVE"
    assert apply_injuries(free_agents, None, None).iloc[0]["injury_status"] is None


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


# --- Our projections ------------------------------------------------------------------


def our_lines():
    """Per-game lines by ESPN player id, as projections.latest returns them."""
    lines = pd.DataFrame(
        [{"espn_player_id": 7, "PTS": 20.0, "FGA": 15.0, "REB": 6.0, "GP": 70.0},
         {"espn_player_id": 8, "PTS": 10.0, "FGA": 8.0, "REB": 3.0, "GP": 60.0}]
    )  # fmt: skip
    return lines.set_index("espn_player_id")


def test_our_projections_fill_the_projected_window_for_pool_players_only():
    df = transform_projected_stats(our_lines(), [7, 99], LEAGUE, SEASON, AT, ["PTS", "GP", "AST"])
    assert set(df["player_id"]) == {7}  # 8 isn't in the pool; 99 has no projection
    assert (df["stat_window"] == "projected").all()
    assert dict(zip(df["stat"], df["value"], strict=True)) == {"PTS": 20.0, "GP": 70.0}


def test_our_projected_points_use_the_leagues_values():
    df = transform_projected_points(our_lines(), [7, 8], SCORING, LEAGUE, SEASON, AT)
    rows = df.set_index("player_id")
    assert rows.at[7, "fp_per_game"] == 20.0 - 15.0 + 6.0
    assert rows.at[7, "fp_total"] == 11.0 * 70 and rows.at[7, "games"] == 70
    assert (rows["source"] == "computed").all() and (rows["stat_window"] == "projected").all()


def test_no_projections_yet_adds_nothing():
    empty = pd.DataFrame(columns=["PTS", "GP"])
    assert transform_projected_stats(empty, [7], LEAGUE, SEASON, AT).empty
    assert transform_projected_points(None, [7], SCORING, LEAGUE, SEASON, AT).empty


def test_games_played_scores_once_per_game_and_missing_stats_count_zero():
    from ingest.transform import computed_points

    line = {"PTS": 20.0, "GP": 10.0}
    scoring = [{"stat": "PTS", "points": 1.0}, {"stat": "GP", "points": 2.0},
               {"stat": "EJ", "points": -5.0}]  # fmt: skip
    assert computed_points(line, scoring) == 22.0


def test_points_for_stats_we_cant_count_are_not_flagged():
    from ingest.transform import points_mismatches, transform_player_points

    scoring = [*SCORING, {"stat": "EJ", "points": -5.0}]
    avg = {"PTS": 20.0, "FGA": 15.0, "REB": 6.0, "EJ": 0.2}  # ejected in 1 of 5 games
    espn_side = {"applied_avg": 10.0, "applied_total": 80.0, "avg": avg, "total": {"GP": 8.0}}
    espn = transform_player_points([make_player(7, {f"{SEASON}_total": espn_side})], scoring,
                                   LEAGUE, SEASON, AT)  # fmt: skip
    assert espn.iloc[0]["uncounted_per_game"] == -1.0
    ours = transform_window_points(windows(), [7], scoring, LEAGUE, SEASON, AT)  # 11.0 a game
    season = ours.loc[ours["stat_window"] == "season"]
    assert points_mismatches(espn, season).empty  # 10 + 1 for the ejection = our 11
    assert len(points_mismatches(espn.drop(columns="uncounted_per_game"), season)) == 1


def test_points_alert_fires_only_on_a_large_share():
    from ingest.transform import ALERT_MARKER, points_alert

    assert points_alert(5, None) is None
    assert points_alert(5, {"checked": 40, "mismatched": 30}) is None  # too few to judge
    assert points_alert(5, {"checked": 800, "mismatched": 100}) is None  # 12.5%: normal
    alert = points_alert(5, {"checked": 800, "mismatched": 300})
    assert alert.startswith(f"{ALERT_MARKER} league 5: 300 of 800 player windows (38%)")
