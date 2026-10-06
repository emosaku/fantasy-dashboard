"""The Trade & Waiver Analyzer's math (app/analysis/) on the synthetic 4-team league
in tests/fixtures/four_team_league.py."""

import numpy as np
import pandas as pd
import pytest

from analysis.explain import explain
from analysis.objective import expected_category_wins, matchup_record
from analysis.pool import team_totals
from analysis.trades import find_trades, simulate_trade
from analysis.waivers import rank_waiver_moves
from analysis.weights import compute_weights, punts
from tests.fixtures.four_team_league import COLUMNS, build_players


@pytest.fixture
def players():
    return build_players()


@pytest.fixture
def totals(players):
    return team_totals(players)


def all_weights(totals, **kwargs):
    return {t: compute_weights(totals, t, **kwargs) for t in totals.index}


def test_totals_leave_out_ir_and_free_agents(players, totals):
    assert list(totals.index) == [1, 2, 3, 4]
    team4 = players.loc[[40, 42, 43], COLUMNS].sum()  # 41 is on IR
    assert np.allclose(totals.loc[4], team4)


def test_runaway_leader_gets_d_zero_and_lock(totals):
    blk = compute_weights(totals, 1).loc["BLK"]
    assert blk["rank"] == 1
    assert blk["down"] == 0
    assert blk["tier"] == "Lock"


def test_team_trailing_by_more_than_delta_gets_u_zero_and_punt(totals):
    ast = compute_weights(totals, 4).loc["AST"]
    assert ast["rank"] == 4
    assert ast["up"] == 0
    assert ast["tier"] == "Punt"
    assert ast["weight"] == 0


def test_weights_average_one(totals):
    assert compute_weights(totals, 2)["weight"].sum() == pytest.approx(9)


def test_punting_zeroes_the_weight_and_drops_it_from_e(totals):
    weights = compute_weights(totals, 2, overrides={"PTS": "Punt"})
    assert weights.loc["PTS", "weight"] == 0
    assert weights.loc["PTS", "tier"] == "Punt"
    with_pts = expected_category_wins(totals, 2)
    without = expected_category_wins(totals, 2, punts(weights))
    pts_wins = expected_category_wins(totals, 2) - expected_category_wins(totals, 2, ["PTS"])
    assert without == pytest.approx(with_pts - pts_wins - _other_punts(weights, totals, 2))


def _other_punts(weights, totals, team):
    others = [c for c in punts(weights) if c != "PTS"]
    return expected_category_wins(totals, team) - expected_category_wins(totals, team, others)


def test_overrides_set_pre_scaling_weights(totals):
    weights = compute_weights(totals, 2, overrides={c: "Swing" for c in COLUMNS} | {"REB": "Lock"})
    # 8 Swing at 1.5 and 1 Lock at 0.5, scaled to sum to 9.
    assert weights.loc["REB", "weight"] == pytest.approx(0.5 * 9 / 12.5)
    assert weights.loc["PTS", "weight"] == pytest.approx(1.5 * 9 / 12.5)


def test_e_is_symmetric(totals):
    n = len(totals)
    assert sum(expected_category_wins(totals, t) for t in totals.index) == pytest.approx(
        9 * n * (n - 1) / 2
    )


def test_matchup_record_covers_every_opponent(totals):
    assert sum(matchup_record(totals, 1)) == 3


def test_trade_inside_a_punt_category_changes_nothing_for_that_team(players, totals):
    # Team 4 punts AST. Give team 2 a copy of team 4's player 40 who differs only in
    # AST, and swap them: for team 4 only AST moves, so its E can't change.
    players = players.copy()
    players.loc[20, COLUMNS] = players.loc[40, COLUMNS]
    players.loc[20, "AST"] = players.loc[40, "AST"] + 2.0
    totals = team_totals(players)
    punts_4 = punts(compute_weights(totals, 4))
    assert "AST" in punts_4

    _, team4, _ = simulate_trade(players, totals, 4, 2, give=[40], get=[20], punts_me=punts_4)
    assert team4.delta_e == 0


def test_find_trades_only_returns_win_win_deals(players, totals):
    deals = find_trades(players, totals, 2, all_weights(totals), top=1000)
    assert not deals.empty
    assert (deals["dE_me"] > 0).all()
    assert (deals["dE_them"] >= 0).all()


def test_simulated_trade_matches_the_finder(players, totals):
    weights = all_weights(totals)
    deals = find_trades(players, totals, 2, weights, top=1000)
    for deal in deals.itertuples():
        _, mine, theirs = simulate_trade(
            players,
            totals,
            2,
            deal.partner_id,
            give=deal.give_ids,
            get=deal.get_ids,
            my_drop=deal.my_drop_id,
            their_drop=deal.their_drop_id,
            my_add=deal.my_add_id,
            their_add=deal.their_add_id,
            punts_me=punts(weights[2]),
            punts_them=punts(weights[deal.partner_id]),
        )
        assert mine.delta_e == pytest.approx(deal.dE_me)
        assert theirs.delta_e == pytest.approx(deal.dE_them)


def test_two_for_one_receiver_drops_its_lowest_valued_player(players, totals):
    deals = find_trades(players, totals, 2, all_weights(totals), top=1000)
    two_for_one = deals.loc[deals["give_ids"].map(len) == 2]
    for deal in two_for_one.itertuples():
        assert not pd.isna(deal.their_drop_id)
        assert deal.their_drop_id not in deal.get_ids  # never the one they gave away


def test_side_left_short_fills_the_slot_from_free_agents(players, totals):
    deals = find_trades(players, totals, 2, all_weights(totals), top=1000)
    for deal in deals.itertuples():
        gave_two, got_two = len(deal.give_ids) == 2, len(deal.get_ids) == 2
        assert pd.isna(deal.my_add_id) != gave_two  # I add a free agent only if short
        assert pd.isna(deal.their_add_id) != got_two
        if gave_two:
            assert deal.my_add_id != 102  # never an OUT player


def test_waivers_skip_out_players_and_find_the_steals_specialist(players, totals):
    moves = rank_waiver_moves(players, totals, 3, compute_weights(totals, 3), top=50)
    assert 102 not in set(moves["add_id"])  # OUT, however good
    assert moves.iloc[0]["add_id"] == 103
    assert 41 not in set(moves["drop_id"])  # IR players aren't dropped


def test_waiver_delta_matches_a_simulated_move(players, totals):
    weights = compute_weights(totals, 3)
    best = rank_waiver_moves(players, totals, 3, weights).iloc[0]
    _, mine, _ = simulate_trade(
        players,
        totals,
        3,
        None,
        give=[best["drop_id"]],
        get=[best["add_id"]],
        punts_me=punts(weights),
    )
    assert mine.delta_e == pytest.approx(best["dE"])


def test_explanation_counts_gains_and_losses():
    text = explain(pd.Series({"BLK": 2.0, "FG%": 1.0, "3PM": -1.0}))
    assert text == "+2 category wins: passes 2 teams in BLK, 1 in FG%; costs 1 team in 3PM."
    assert explain({}) == "No change in category wins."
