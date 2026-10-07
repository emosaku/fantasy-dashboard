"""The points engine (app/points) on the synthetic league in
tests/fixtures/points_league.py, with brute-force oracles for the math."""

import itertools
import math

import numpy as np
import pandas as pd
import pytest

from points import lineup, model, trades
from points.trades import CLOSE_CALL, MAX_GAIN, WIN_WIN
from tests.fixtures import points_league as fx


def setup(results=None):
    return trades.build(
        fx.build_players(), fx.schedule(), fx.SLOTS, fx.BENCH, current_week=1, last_week=3,
        as_of=fx.OPENING, results=fx.results() if results is None else results,
    )  # fmt: skip


@pytest.fixture(scope="module")
def league():
    return setup()


# --- Start chances and the fast estimate ------------------------------------------------


def brute_weekly(fpg, play, slots):
    """Expected points on one day: every subset of players playing, the best `slots`
    of them start (positions ignored)."""
    total = 0.0
    n = len(fpg)
    for mask in itertools.product([0, 1], repeat=n):
        prob = math.prod(q if m else 1 - q for q, m in zip(play, mask, strict=True))
        playing = sorted((f for f, m in zip(fpg, mask, strict=True) if m), reverse=True)
        total += prob * sum(playing[:slots])
    return total


@pytest.mark.parametrize("seed", range(5))
def test_fast_estimate_is_the_exact_expectation_without_positions(seed):
    rng = np.random.default_rng(seed)
    n, slots, days = 7, 3, 7.0
    fpg = rng.uniform(5, 40, n)
    games = rng.integers(0, 8, n).astype(float)
    expected = days * brute_weekly(fpg, games / days, slots)
    assert model.fast_weekly_points(fpg, games, days, slots) == pytest.approx(expected)


def test_fast_estimate_works_on_many_rosters_at_once():
    rng = np.random.default_rng(3)
    fpg, games = rng.uniform(5, 40, (4, 6)), rng.integers(0, 5, (4, 6)).astype(float)
    batch = model.fast_weekly_points(fpg, games, 7.0, 3)
    one_by_one = [model.fast_weekly_points(f, g, 7.0, 3) for f, g in zip(fpg, games, strict=True)]
    assert batch == pytest.approx(one_by_one)


def test_everyone_starts_when_there_are_enough_slots():
    fpg, games = np.array([30.0, 20.0, 10.0]), np.array([3.0, 4.0, 2.0])
    assert model.fast_weekly_points(fpg, games, 7.0, 5) == pytest.approx(90 + 80 + 20)


# --- The daily lineup --------------------------------------------------------------------


def brute_lineup(players, fpg, slots_of, counts):
    """Best total over every set of players that can be seated."""
    seats = [s for s, c in counts.items() for _ in range(c)]
    best = 0.0
    for size in range(len(seats) + 1):
        for group in itertools.combinations(players, size):
            for order in itertools.permutations(seats, size):
                if all(slot in slots_of[p] for p, slot in zip(group, order, strict=True)):
                    best = max(best, sum(max(fpg[p], 0) for p in group))
                    break
    return best


@pytest.mark.parametrize("seed", range(6))
def test_greedy_lineup_is_optimal(seed):
    rng = np.random.default_rng(seed)
    kinds = [frozenset({"G", "UT"}), frozenset({"F", "UT"}), frozenset({"G", "F", "UT"}),
             frozenset({"C"}), frozenset({"F", "C", "UT"})]  # fmt: skip
    players = list(range(7))
    fpg = {p: float(rng.uniform(-5, 40)) for p in players}
    slots_of = {p: kinds[rng.integers(0, len(kinds))] for p in players}
    counts = {"G": 1, "F": 1, "C": 1, "UT": 2}
    chosen = lineup.best_lineup(players, fpg, slots_of, counts)
    assert sum(fpg[p] for p in chosen) == pytest.approx(
        brute_lineup(players, fpg, slots_of, counts)
    )


def test_simulation_counts_each_day_and_skips_injured_weeks():
    fpg = {1: 30.0, 2: 20.0, 3: 10.0}
    slots_of = {1: frozenset({"G"}), 2: frozenset({"G"}), 3: frozenset({"F"})}
    team_of = {1: "AAA", 2: "BBB", 3: "AAA"}
    days = [(1, frozenset({"AAA", "BBB"})), (1, frozenset({"BBB"})), (2, frozenset({"AAA"}))]
    out = lineup.simulate_weeks([1, 2, 3], fpg, slots_of, team_of, {1: 2, 2: 1, 3: 1},
                                {"G": 1, "F": 1}, days)  # fmt: skip
    # Day 1: player 1 is out until week 2, so 2 (G) and 3 (F) start; day 2: 2 only;
    # week 2: 1 and 3.
    assert out["weeks"] == {1: 50.0, 2: 40.0}
    assert out["starts"] == {1: 1, 2: 2, 3: 2}


# --- Expected wins and the spread ----------------------------------------------------------


def test_expected_wins_matches_the_formula_and_splits_every_pairing():
    mu = pd.Series({1: 500.0, 2: 520.0, 3: 480.0, 4: 505.0})
    sigma = 40.0
    e = model.expected_wins(mu, sigma)
    for i in mu.index:
        direct = sum(
            0.5 * (1 + math.erf((mu[i] - mu[j]) / math.sqrt(2 * sigma**2) / math.sqrt(2)))
            for j in mu.index
            if j != i
        )
        assert e[i] == pytest.approx(direct, abs=1e-6)
    assert e.sum() == pytest.approx(6.0)  # 4 teams: 6 pairings, each worth one win


def test_spread_comes_from_played_weeks_once_there_are_three():
    mu = pd.Series({1: 100.0, 2: 100.0})
    few = pd.DataFrame({"matchup_period": [1, 1], "team_id": [1, 2], "points": [90.0, 110.0],
                        "is_playoff": [False, False]})  # fmt: skip
    sigma, note = model.weekly_spread(few, mu)
    assert sigma == pytest.approx(12.0) and "early" in note
    played = pd.DataFrame(
        {
            "matchup_period": [1, 1, 2, 2, 3, 3],
            "team_id": [1, 2, 1, 2, 1, 2],
            "points": [90.0, 100.0, 110.0, 100.0, 100.0, 130.0],
            "is_playoff": [False] * 6,
        }
    )
    sigma, note = model.weekly_spread(played, mu)
    residuals = [-10, 10, 0, -10, -10, 20]  # around each team's own mean (100, 110)
    assert sigma == pytest.approx(math.sqrt(sum(r * r for r in residuals) / 4))
    assert "3 weeks" in note


# --- Standings, all-play and luck ----------------------------------------------------------


def scores_table():
    """Two weeks: week 1 team 1 beats 2 (120-100), 3 beats 4 (90-80); week 2 team 1
    loses to 3 (95-130), 2 beats 4 (105-70); week 3 (current) is in progress."""
    rows = [(1, 1, 2, 120, 100), (1, 3, 4, 90, 80), (2, 1, 3, 95, 130), (2, 2, 4, 105, 70),
            (3, 1, 4, 40, 30), (3, 2, 3, 20, 25)]  # fmt: skip
    out = []
    for week, a, b, pa, pb in rows:
        out.append((week, a, b, pa, pb, False))
        out.append((week, b, a, pb, pa, False))
    return pd.DataFrame(out, columns=["matchup_period", "team_id", "opponent_id", "points",
                                      "opponent_points", "is_playoff"])  # fmt: skip


def test_season_table_counts_records_all_play_and_luck():
    table = model.season_table(model.played_results(scores_table(), current_week=3))
    one = table.loc[1]
    assert (one["wins"], one["losses"], one["ties"]) == (1, 1, 0)
    # All-play: week 1 team 1 scored the most (3-0); week 2 it beat 4 only (1-2).
    assert (one["ap_wins"], one["ap_losses"]) == (4, 2)
    assert one["luck"] == pytest.approx(0.5 - 4 / 6)
    assert table.loc[3, "points_for"] == 220
    assert table["weeks"].eq(2).all()  # the current week isn't counted


def test_luck_by_week_runs_to_date():
    weekly = model.luck_by_week(model.played_results(scores_table(), current_week=3))
    four = weekly.loc[weekly["team_id"] == 4].set_index("matchup_period")
    assert four.at[1, "luck"] == pytest.approx(0 - 0)  # lowest score and lost
    assert four.at[2, "actual_to_date"] == 0


def test_projected_finish_keeps_played_weeks_and_spreads_the_rest():
    scores = scores_table()
    mu = pd.Series({1: 100.0, 2: 100.0, 3: 100.0, 4: 100.0})
    finish = model.projected_finish(scores, mu, 20.0, current_week=3, last_week=3,
                                    current_share_left=0.5)  # fmt: skip
    assert (finish["wins"] + finish["losses"] + finish["ties"]).eq(3).all()
    # Team 1 leads 40-30 with half a week left between equal teams: better than even.
    assert 1 + 0.5 < finish.at[1, "wins"] < 2
    # 1 won week 1, 4 lost both; this week one of them wins it.
    assert finish.at[1, "wins"] + finish.at[4, "wins"] == pytest.approx(1 + 0 + 1)


# --- Players -----------------------------------------------------------------------------


def test_blend_moves_from_projection_to_season_by_games_played():
    season = pd.Series([30.0, 30.0, np.nan, 25.0])
    projected = pd.Series([20.0, 20.0, 22.0, np.nan])
    games = pd.Series([5.0, 40.0, 0.0, 3.0])
    out = model.blend(season, projected, games)
    assert list(out) == pytest.approx([22.5, 30.0, 22.0, 25.0])


def test_replacement_is_the_median_of_the_best_healthy_free_agents():
    players = fx.build_players()
    # Healthy free agents: 101 (24.0) and 103 (21.5); 102 (40.0) is OUT.
    assert model.replacement_level(players) == pytest.approx(22.75)


def test_points_by_source_groups_stats_and_puts_bonuses_in_other():
    scoring = [{"stat": "PTS", "points": 1.0}, {"stat": "FGA", "points": -1.0},
               {"stat": "REB", "points": 1.0}, {"stat": "DD", "points": 5.0}]  # fmt: skip
    lines = pd.DataFrame({"PTS": [20.0], "FGA": [15.0], "REB": [10.0]}, index=[7])
    by_stat = model.points_by_stat(lines, scoring)
    sources = model.points_by_source(by_stat, scoring, espn_fpg=pd.Series({7: 18.0}))
    row = sources.loc[7]
    assert (row["Scoring"], row["Rebounds"], row["Misses and turnovers"]) == (20, 10, -15)
    assert row["Other"] == pytest.approx(3.0)  # ESPN's 18 minus our 15: a bonus
    assert row.sum() == pytest.approx(18.0)


def test_games_by_week_follow_the_schedule_and_injuries(league):
    p = league.players
    for pid in (10, 21, 33):
        games = len(fx.DAYS[p.at[pid, "pro_team"]])
        assert p.at[pid, "games"] == games and p.at[pid, "games_left"] == 3 * games
    out = p.loc[(p["team_id"] == 3) & (p["injury_status"] == "OUT")]
    assert (out["back"] == 3).all()  # OUT, no return date: back in 2 weeks
    week_games = model.week_games(fx.schedule(), [1, 2, 3])
    assert (out["games_left"] == [week_games.at[t, 3] for t in out["pro_team"]]).all()


# --- Trades: the vectorized scores are the one-at-a-time scores -------------------------------


def one_at_a_time(league, me, deal):
    """A deal scored on its own with the fast estimate."""
    mine, theirs = trades.after_rosters(league, me, deal)
    them = int(deal["partner_id"])
    base = league.team_mu(full=False)
    after = base.copy()
    after[me], after[them] = league.fast_mu(mine), league.fast_mu(theirs)
    change = model.expected_wins(after, league.sigma) - model.expected_wins(base, league.sigma)
    return after[me] - base[me], after[them] - base[them], change[me], change[them]


@pytest.mark.parametrize("me,them", [(1, 3), (2, 4), (3, 1)])
def test_vectorized_deal_scores_equal_scoring_each_deal_alone(league, me, them):
    deals = trades.score_pair(league, me, them, (1, 2), (1, 2), gains_only=False)

    def packages(team):
        n = len(league.roster(team))  # IR players are left out
        return n + math.comb(n, 2)

    assert len(deals) == packages(me) * packages(them)
    for _, deal in deals.sample(60, random_state=0).iterrows():
        expected = one_at_a_time(league, me, deal)
        got = (deal["dmu_me"], deal["dmu_them"], deal["dE_me"], deal["dE_them"])
        assert got == pytest.approx(expected, abs=1e-6)


def test_rosters_stay_full_and_drops_are_the_lowest_own_players(league):
    deals = trades.score_pair(league, 1, 3, (1, 2), (1, 2), gains_only=False)
    p = league.players
    for _, deal in deals.iterrows():
        mine, theirs = trades.after_rosters(league, 1, deal)
        assert len(mine) == len(league.roster(1)) and len(theirs) == len(league.roster(3))
        if deal["my_drop_ids"]:
            kept_own = [x for x in league.roster(1) if x not in deal["give_ids"]]
            lowest = sorted(kept_own, key=lambda x: p.at[x, "fpg"])[: len(deal["my_drop_ids"])]
            assert set(deal["my_drop_ids"]) == set(lowest)
            assert not set(deal["my_drop_ids"]) & set(deal["get_ids"])
        for fa in deal["my_add_ids"] + deal["their_add_ids"]:
            assert p.at[fa, "injury_status"] != "OUT"


def test_rescore_is_the_full_simulation(league):
    deals = trades.score_pair(league, 1, 3, (1, 2), (1, 2))
    best = trades.rescore(league, 1, deals, top=5)
    for _, deal in best.iterrows():
        mine, theirs = trades.after_rosters(league, 1, deal)
        before, after, change = trades.full_scores(league, {1: mine, 3: theirs})
        assert deal["dE_me"] == pytest.approx(change[1])
        assert deal["dmu_them"] == pytest.approx(after[3] - before[3])
        assert deal["full"]


def test_fast_and_full_rank_deals_alike(league):
    deals = trades.score_pair(league, 1, 3, (1, 2), (1, 2), gains_only=False)
    sample = deals.sample(40, random_state=1)
    full = trades.rescore(league, 1, sample, top=40)
    ranks = pd.DataFrame({"fast": sample.sort_index()["dmu_me"].rank(),
                          "full": full.sort_index()["dmu_me"].rank()})  # fmt: skip
    assert ranks["fast"].corr(ranks["full"]) > 0.8  # Spearman: correlation of ranks


# --- The searches ------------------------------------------------------------------------------


def test_trade_finder_finds_win_wins_for_both_sides(league):
    deals = trades.find_trades(league, 1)
    assert not deals.empty
    assert (deals["dE_me"] > 0).all() and (deals["dE_them"] >= 0).all()
    assert not deals["lopsided"].any() and deals["full"].all()
    assert list(deals["dE_me"]) == sorted(deals["dE_me"], reverse=True)


def test_a_team_with_injured_players_drops_them_first(league):
    deals = trades.score_pair(league, 3, 1, (1,), (2,), gains_only=False)
    out = set(league.players.index[league.players["injury_status"] == "OUT"])
    assert deals["my_drop_ids"].map(lambda d: set(d) <= out).all()


def test_acceptance_levels_nest(league):
    every = {
        level: trades.build_offers(
            league,
            2,
            league.roster(2),
            [1, 3, 4],
            acceptance=level,
            top=10_000,
            per_team_cap=10_000,
            rescore_top=10_000,
        )  # fmt: skip
        for level in (WIN_WIN, CLOSE_CALL, MAX_GAIN)
    }

    def keys(df):
        return set(zip(df["partner_id"], df["give_ids"], df["get_ids"], strict=True))

    def covered(smaller_level, larger_level):
        """Every deal at the stricter level is at the looser one, or replaced there by
        the same deal minus a player I get that gains me as much (near-duplicates)."""
        looser = {k: g for k, g in zip(keys_list(every[larger_level]),
                                        every[larger_level]["dE_me"], strict=True)}  # fmt: skip
        for (them, give, get), gain in zip(keys_list(every[smaller_level]),
                                           every[smaller_level]["dE_me"], strict=True):  # fmt: skip
            if (them, give, get) in looser:
                continue
            assert any(
                looser.get((them, give, tuple(x for x in get if x != p)), -1) >= gain - 1e-9
                for p in get
            ), (them, give, get)

    def keys_list(df):
        return list(zip(df["partner_id"], df["give_ids"], df["get_ids"], strict=True))

    covered(WIN_WIN, CLOSE_CALL)
    covered(CLOSE_CALL, MAX_GAIN)
    assert len(keys(every[WIN_WIN])) < len(keys(every[MAX_GAIN]))
    assert (every[CLOSE_CALL]["dE_them"] >= trades.CLOSE_CALL_FLOOR - 1e-9).all()
    assert not every[CLOSE_CALL]["lopsided"].any()
    assert (every[MAX_GAIN]["dE_me"] > 0).all()


def test_offers_only_send_block_players_and_cap_per_team(league):
    block = league.roster(2)[:3]
    deals = trades.build_offers(league, 2, block, [1, 3, 4], acceptance=MAX_GAIN)
    assert not deals.empty
    assert all(set(g) <= set(block) for g in deals["give_ids"])
    assert deals["partner_id"].value_counts().max() <= trades.OFFERS_PER_TEAM_CAP


def test_the_guard_trips_before_any_work(league):
    with pytest.raises(trades.SearchTooLarge, match="limit"):
        trades.build_offers(league, 2, league.roster(2), [1, 3, 4], max_give=3, max_get=3,
                            max_search=100)  # fmt: skip


def test_deals_for_a_target_always_bring_him_and_are_labelled(league):
    deals = trades.deals_for_target(league, 2, 30)
    assert not deals.empty
    assert all(30 in g for g in deals["get_ids"])
    for _, deal in deals.iterrows():
        assert deal["status"] == trades.status(deal)
    order = deals["status"].map(trades.STATUS_ORDER)
    assert list(order) == sorted(order)


def test_waiver_moves_match_the_mock_trade(league):
    moves = trades.waiver_moves(league, 3)
    assert not moves.empty and (moves["dE"] > 0).all()
    move = moves.iloc[0]
    drop = [] if pd.isna(move["drop_id"]) else [int(move["drop_id"])]
    mock = trades.mock(league, 3, None, my_add=[int(move["add_id"])], my_drop=drop)
    assert mock["dE"][3] == pytest.approx(move["dE"])


def test_mock_trade_is_symmetric_with_the_search(league):
    deal = trades.find_trades(league, 1).iloc[0]
    them = int(deal["partner_id"])
    moves = {"my_add": deal["my_add_ids"], "my_drop": deal["my_drop_ids"],
             "their_add": deal["their_add_ids"], "their_drop": deal["their_drop_ids"]}  # fmt: skip
    out = trades.mock(league, 1, them, deal["give_ids"], deal["get_ids"], **moves)
    assert out["dE"][1] == pytest.approx(deal["dE_me"])
    assert out["dE"][them] == pytest.approx(deal["dE_them"])
    assert out["e_after"].sum() == pytest.approx(6.0)
