"""Three-team trades (app/analysis/three_team.py) on the synthetic 4-team league in
tests/fixtures/four_team_league.py, plus reshuffled copies of it.

The key check: the vectorized search scores every deal exactly as simulating that
deal on its own does, so it finds what checking each combination one at a time finds."""

import functools
import itertools

import numpy as np
import pandas as pd
import pytest

from analysis.explain import group_pitch
from analysis.pool import team_totals
from analysis.three_team import (
    LOPSIDED_GAP,
    _context,
    _packages,
    _score_grid,
    _side,
    circle_moves,
    middle_plans,
    partner_shortlist,
    simulate_circle,
    three_team_for_target,
    three_team_offers,
)
from analysis.trades import (
    CLOSE_CALL,
    MAX_GAIN,
    WIN_WIN,
    SearchTooLarge,
    best_pickup,
    contribution,
    fill_roster,
    find_trades,
    simulate_trade,
)
from analysis.weights import compute_weights, generic_values, punts
from categories import COLUMNS
from tests.fixtures.four_team_league import build_players

EVERYTHING = {"top": 10_000, "per_pair_cap": 10_000}


def league(seed=None):
    players = build_players()
    if seed is not None:  # same shape, new numbers
        rng = np.random.default_rng(seed)
        rostered = players["team_id"].notna()
        players.loc[rostered, COLUMNS] += rng.normal(0, 0.6, (rostered.sum(), len(COLUMNS)))
    totals = team_totals(players)
    return players, totals, {t: compute_weights(totals, t) for t in totals.index}


@pytest.fixture
def base():
    return league()


def active(players, team):
    return [int(p) for p in players.index[(players["team_id"] == team) & ~players["is_ir"]]]


@functools.cache
def every_deal(seed, me, target):
    """Every deal in every Unlock circle, simulated one at a time:
    {(circle, packages): ((dE me, a, b), fair)}."""
    players, totals, weights = league(seed)
    generic = generic_values(players)
    out = {}
    for circle, packs in unlock_circles(players, me, target).items():
        for packages in itertools.product(*packs):
            result = simulate_circle(players, totals, circle, packages, weights)
            moves = circle_moves(circle, packages)
            fair = all(
                abs(generic[list(s)].sum() - generic[list(g)].sum()) <= LOPSIDED_GAP
                for s, g in (moves[t] for t in circle[1:])
            )
            out[(circle, packages)] = (tuple(result.sides[t].delta_e for t in circle), fair)
    return out


def passing(seed, me, target, acceptance):
    floor = {WIN_WIN: 0.0, CLOSE_CALL: -2.0, MAX_GAIN: -np.inf}[acceptance]
    return {
        key: d
        for key, (d, fair) in every_deal(seed, me, target).items()
        if d[0] > 1e-9 and min(d[1:]) > floor - 1e-9 and (fair or acceptance == MAX_GAIN)
    }


def unlock_circles(players, me, target):
    them = int(players.at[target, "team_id"])
    p_them = _packages([target, *[p for p in active(players, them) if p != target]], 2, target)
    thirds = [t for t in (1, 2, 3, 4) if t not in (me, them)]
    p_me = _packages(active(players, me), 2)
    return {(me, t, them): (p_me, _packages(active(players, t), 2), p_them) for t in thirds}


# --- The fast search equals checking every deal --------------------------------------


@pytest.mark.parametrize("seed", [None, 1, 2])
def test_grid_scores_every_deal_exactly_like_simulating_it(seed):
    players, totals, weights = league(seed)
    circle, packs = next(iter(unlock_circles(players, 2, 30).items()))
    generic, fa_order, masks, max_k = _context(players, weights, 2)
    sides = tuple(
        _side(players, t, p, weights[t], generic, max_k, fa_order)
        for t, p in zip(circle, packs, strict=True)
    )
    d_me, d_a, d_b = _score_grid(totals, sides, masks)
    for i, p_me in enumerate(packs[0]):
        for j, p_a in enumerate(packs[1]):
            for k, p_b in enumerate(packs[2]):
                result = simulate_circle(players, totals, circle, (p_me, p_a, p_b), weights)
                me, a, b = circle
                assert d_me[i, j, k] == pytest.approx(result.sides[me].delta_e)
                assert d_a[i, j, k] == pytest.approx(result.sides[a].delta_e)
                assert d_b[i, j, k] == pytest.approx(result.sides[b].delta_e)


@pytest.mark.parametrize("seed", [None, 3])
@pytest.mark.parametrize("acceptance", [WIN_WIN, CLOSE_CALL, MAX_GAIN])
def test_unlock_finds_what_checking_every_deal_finds(seed, acceptance):
    players, totals, weights = league(seed)
    deals = three_team_for_target(players, totals, 2, 30, weights, acceptance=acceptance,
                                  **EVERYTHING)  # fmt: skip
    passing_deals = passing(seed, 2, 30, acceptance)
    returned = {
        (r.circle, (r.give_ids, r.a_sends, r.get_ids)): (r.dE_me, r.dE_a, r.dE_b)
        for r in deals.itertuples()
    }
    assert set(returned) <= set(passing_deals)  # everything returned passes
    for key, scores in returned.items():
        assert scores == pytest.approx(passing_deals[key])
    if passing_deals:  # and the best deal there is comes first
        assert deals.iloc[0]["dE_me"] == pytest.approx(max(v[0] for v in passing_deals.values()))
    # Every passing_deals deal is returned unless a version with one player fewer is
    # returned instead (the near-duplicate rule).
    for (circle, packs), scores in passing_deals.items():
        if (circle, packs) in returned:
            continue
        smaller = [
            (circle, tuple(tuple(x for x in pk if x != p) if n == m else pk
                           for m, pk in enumerate(packs)))
            for n, pack in enumerate(packs) if len(pack) > 1 for p in pack
        ]  # fmt: skip
        assert any(s in passing_deals and passing_deals[s][0] >= scores[0] - 1e-9 for s in smaller)


# --- Acceptance, ranking, caps ----------------------------------------------------------


def test_every_deal_brings_the_target_and_i_gain(base):
    players, totals, weights = base
    deals = three_team_for_target(players, totals, 2, 30, weights, acceptance=MAX_GAIN)
    assert not deals.empty
    assert all(30 in r.get_ids for r in deals.itertuples())
    assert (deals["dE_me"] > 0).all()
    assert all(set(r.give_ids) <= set(active(players, 2)) for r in deals.itertuples())


def test_acceptance_levels(base):
    players, totals, weights = base
    every = {
        level: three_team_for_target(
            players, totals, 2, 30, weights, acceptance=level, **EVERYTHING
        )  # fmt: skip
        for level in (WIN_WIN, CLOSE_CALL, MAX_GAIN)
    }

    def keys(df):
        return {(r.circle, r.give_ids, r.a_sends, r.get_ids) for r in df.itertuples()}

    win_win, close, max_gain = (every[x] for x in (WIN_WIN, CLOSE_CALL, MAX_GAIN))
    assert (win_win[["dE_a", "dE_b"]] >= 0).all().all()
    assert (close[["dE_a", "dE_b"]] >= -2).all().all()
    assert not (close["lopsided_a"] | close["lopsided_b"]).any()
    # A deal costing a partner a little: out at Win-win, in at Close call.
    costs_a_little = max_gain.loc[
        (max_gain[["dE_a", "dE_b"]].min(axis=1).between(-2, -0.5))
        & ~max_gain["lopsided_a"] & ~max_gain["lopsided_b"]
    ]  # fmt: skip
    assert not costs_a_little.empty
    assert keys(costs_a_little) <= keys(close)
    assert not keys(costs_a_little) & keys(win_win)
    # Max gain keeps lopsided deals and flags them.
    assert (max_gain["lopsided_a"] | max_gain["lopsided_b"]).any()


def test_ranked_by_my_gain_then_the_weaker_partner(base):
    players, totals, weights = base
    deals = three_team_for_target(players, totals, 2, 30, weights, acceptance=MAX_GAIN,
                                  **EVERYTHING)  # fmt: skip
    key = list(zip(-deals["dE_me"], -deals[["dE_a", "dE_b"]].min(axis=1), deals["moved"]))
    assert key == sorted(key)


def test_at_most_two_deals_per_pair_of_partners_and_ten_in_all(base):
    players, totals, weights = base
    deals = three_team_offers(players, totals, 2, active(players, 2), weights, acceptance=MAX_GAIN)
    pairs = deals["circle"].map(lambda c: frozenset(c[1:]))
    assert pairs.value_counts().max() <= 2
    assert len(deals) <= 10


def test_min_gain_keeps_only_deals_that_beat_the_two_team_offer(base):
    players, totals, weights = base
    deals = three_team_for_target(players, totals, 2, 30, weights, acceptance=MAX_GAIN,
                                  min_gain=5)  # fmt: skip
    assert (deals["dE_me"] > 5).all()


def test_naming_the_third_team(base):
    players, totals, weights = base
    deals = three_team_for_target(players, totals, 2, 30, weights, third=4, acceptance=MAX_GAIN)
    assert set(deals["partner_a"]) == {4}


def test_one_player_packages(base):
    players, totals, weights = base
    deals = three_team_for_target(players, totals, 2, 30, weights, max_size=1,
                                  acceptance=MAX_GAIN, **EVERYTHING)  # fmt: skip
    assert not deals.empty
    for r in deals.itertuples():
        assert len(r.give_ids) == len(r.a_sends) == len(r.get_ids) == 1


def test_injured_teammates_are_skipped_on_request(base):
    players, totals, weights = base
    players = players.copy()
    players.loc[31, "injury_status"] = "OUT"
    totals = team_totals(players)

    def received(exclude):
        deals = three_team_for_target(players, totals, 2, 30, weights, acceptance=MAX_GAIN,
                                      exclude_injured=exclude, **EVERYTHING)  # fmt: skip
        return {p for r in deals.itertuples() for p in r.get_ids}

    assert 31 not in received(True)
    assert 31 in received(False)


# --- From my trade block ------------------------------------------------------------------


def test_block_deals_only_send_block_players_and_partners_shortlists(base):
    players, totals, weights = base
    block = [20, 21]
    deals = three_team_offers(players, totals, 2, block, weights, acceptance=MAX_GAIN,
                              shortlist=2, **EVERYTHING)  # fmt: skip
    assert not deals.empty
    for r in deals.itertuples():
        _, a, b = r.circle
        assert set(r.give_ids) <= set(block)
        assert set(r.a_sends) <= set(partner_shortlist(players, a, weights[a], 2))
        assert set(r.get_ids) <= set(partner_shortlist(players, b, weights[b], 2))
    assert {frozenset(c[1:]) for c in deals["circle"]} <= {
        frozenset(p) for p in ((1, 3), (1, 4), (3, 4))
    }


def test_block_search_runs_both_directions_and_named_partners(base):
    players, totals, weights = base
    deals = three_team_offers(players, totals, 2, active(players, 2), weights, partners=(3, 4),
                              acceptance=MAX_GAIN, top=40, per_pair_cap=40)  # fmt: skip
    assert set(deals["circle"]) <= {(2, 3, 4), (2, 4, 3)}
    assert len(set(deals["circle"])) == 2
    one = three_team_offers(players, totals, 2, active(players, 2), weights, partners=(3,),
                            acceptance=MAX_GAIN)  # fmt: skip
    assert all(3 in c[1:] for c in one["circle"])


def test_shortlist_skips_out_and_ir_and_prefers_movable_players(base):
    players, totals, weights = base
    players = players.copy()
    players.loc[42, "injury_status"] = "OUT"
    short = partner_shortlist(players, 4, weights[4], 6)
    assert 41 not in short and 42 not in short  # IR, OUT
    rows = players.loc[short]
    surplus = generic_values(rows) - rows[COLUMNS] @ weights[4].loc[COLUMNS, "weight"]
    assert list(surplus) == sorted(surplus, reverse=True)


def test_the_guard_trips_before_any_work(base):
    players, totals, weights = base
    with pytest.raises(SearchTooLarge, match="three-team deals"):
        three_team_for_target(players, totals, 2, 30, weights, max_search=10)
    with pytest.raises(SearchTooLarge):
        three_team_offers(players, totals, 2, active(players, 2), weights, max_search=10)


# --- Rosters stay full, by the two-team rule ------------------------------------------------


def test_rosters_stay_full_for_every_team(base):
    players, totals, weights = base
    deals = some_deals(base)
    uneven = 0
    for r in deals.itertuples():
        packages = (r.give_ids, r.a_sends, r.get_ids)
        for team, (sent, got) in circle_moves(r.circle, packages).items():
            drops, adds = r.fills[team]
            roster = set(active(players, team))
            after = ((roster - set(sent)) | set(got)) - set(drops) | set(adds)
            assert len(after) == len(roster)
            assert not set(drops) & set(got)  # never drops a player it just received
            assert all(players.at[p, "injury_status"] != "OUT" for p in adds)
            uneven += len(sent) != len(got)
    assert uneven


def test_fill_roster_is_the_two_team_rule(base):
    players, totals, weights = base
    deals = find_trades(players, totals, 2, weights, top=1000)
    two_for_one = deals.loc[deals["give_ids"].map(len) == 2]
    assert not two_for_one.empty
    for d in two_for_one.itertuples():
        them = int(d.partner_id)
        assert fill_roster(players, them, d.get_ids, d.give_ids, weights[them]) == (
            (d.their_drop_id,),
            (),
        )
        assert fill_roster(players, 2, d.give_ids, d.get_ids, weights[2]) == (
            (),
            (best_pickup(players, weights[2]),),
        )


# --- Getting it done on ESPN -------------------------------------------------------------


def some_deals(base):
    players, totals, weights = base
    return three_team_offers(players, totals, 2, active(players, 2), weights, acceptance=MAX_GAIN)


def test_every_middle_team_plan_ends_with_the_same_rosters(base):
    players, totals, weights = base
    for r in some_deals(base).itertuples():
        packages = (r.give_ids, r.a_sends, r.get_ids)
        plans = middle_plans(players, totals, r.circle, packages, weights)
        assert {p["middle"] for p in plans} == set(r.circle)
        final = {t: (set(g), set(s)) for t, (s, g) in circle_moves(r.circle, packages).items()}
        for plan in plans:
            net = {t: [set(), set()] for t in r.circle}  # team -> [gets, sends]
            for trade in (plan["trade1"], plan["trade2"]):
                m, x = plan["middle"], trade["with"]
                net[m][0] |= set(trade["middle_gets"])
                net[m][1] |= set(trade["middle_sends"])
                net[x][0] |= set(trade["middle_sends"])
                net[x][1] |= set(trade["middle_gets"])
            for t in r.circle:  # the middle passes one package straight through
                passed = net[t][0] & net[t][1]
                assert (net[t][0] - passed, net[t][1] - passed) == final[t]


def test_the_in_between_score_is_trade_one_on_its_own(base):
    players, totals, weights = base
    for r in some_deals(base).itertuples():
        plans = middle_plans(players, totals, r.circle, (r.give_ids, r.a_sends, r.get_ids), weights)
        assert [p["between"] for p in plans] == sorted((p["between"] for p in plans), reverse=True)
        for plan in plans:
            m, t1 = plan["middle"], plan["trade1"]
            _, mine, theirs = simulate_trade(
                players, totals, m, t1["with"], give=t1["middle_sends"], get=t1["middle_gets"],
                punts_me=punts(weights[m]), punts_them=punts(weights[t1["with"]]),
            )  # fmt: skip
            assert plan["between"] == pytest.approx(mine.delta_e)
            assert plan["between_first"] == pytest.approx(theirs.delta_e)


def test_simulate_circle_with_my_own_moves_matches_the_search(base):
    players, totals, weights = base
    for r in some_deals(base).itertuples():
        me = r.circle[0]
        drops, adds = r.fills[me]
        packages = (r.give_ids, r.a_sends, r.get_ids)
        mock = simulate_circle(players, totals, r.circle, packages, weights, my_drop=list(drops),
                               my_add=list(adds), fill_mine=False)  # fmt: skip
        assert mock.sides[me].delta_e == pytest.approx(r.dE_me)
        assert mock.sides[r.circle[1]].delta_e == pytest.approx(r.dE_a)


def test_all_three_totals_move_and_nobody_else(base):
    players, totals, weights = base
    r = some_deals(base).iloc[0]
    result = simulate_circle(players, totals, r.circle, (r.give_ids, r.a_sends, r.get_ids), weights)
    untouched = [t for t in totals.index if t not in r.circle]
    pd.testing.assert_frame_equal(result.after.loc[untouched], totals.loc[untouched])
    moves = circle_moves(r.circle, (r.give_ids, r.a_sends, r.get_ids))
    for team, (sent, got) in moves.items():
        drops, adds = result.fills[team]
        expected = (
            totals.loc[team].to_numpy()
            + contribution(players, [*got, *adds])
            - contribution(players, [*sent, *drops])
        )
        assert np.allclose(result.after.loc[team].to_numpy(), expected)


# --- The group message ---------------------------------------------------------------------


def test_group_pitch_covers_every_team_and_the_order():
    text = group_pitch(
        [("I", "P30"), ("Team C", "P20"), ("Team B", "P10")],
        [("Team B", {"ast": 1.0, "ft_pct": 0.5}), ("Team C", {"pts": -1.0})],
        "B and I trade first, then B sends P20 to C for P10.",
    )
    assert text.startswith("Three-team idea: I get P30, Team C gets P20, Team B gets P10.")
    assert "Team B, it helps your AST and FT%." in text
    assert "Team C, it costs you 1 category wins." in text
    assert text.endswith("Easiest order: B and I trade first, then B sends P20 to C for P10.")
