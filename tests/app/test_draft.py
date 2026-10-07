"""The draft tool (app/draft): draft state and pick entry, the pool and its board,
the simulations, the recommendations and the calibration, on small synthetic pools
where the right answer is known."""

import ast
import datetime as dt
import math
import pathlib

import numpy as np
import pandas as pd
import pytest

from draft import calibrate, recommend, simulate, store
from draft import pool as dpool
from draft.formats import DraftFormat, PointsFormat
from draft.simulate import OpponentModel
from draft.state import (
    Draft,
    DraftError,
    Order,
    matches,
    merge_official,
    normalize,
    parse_paste,
)
from points import model as points_model
from tests.fixtures.fake_firestore import FakeFirestore

EXACT = OpponentModel(noise_base=0.0, noise_share=0.0, cap_share=1.0)  # no noise, no caps


# --- Draft state ---------------------------------------------------------------------------


def test_snake_order_reverses_every_round():
    order = Order((7, 3, 5), rounds=3)
    assert [order.owner(k) for k in range(1, 10)] == [7, 3, 5, 5, 3, 7, 7, 3, 5]
    assert order.round_of(4) == (2, 1) and order.total == 9
    assert order.picks_of(3) == [2, 5, 8]
    assert [Order((7, 3, 5), 2, snake=False).owner(k) for k in range(1, 7)] == [7, 3, 5] * 2


def test_picks_undo_and_rosters():
    draft = Draft(Order((1, 2), rounds=2))
    draft.add(10)
    draft.add(20, team=1)  # a traded pick: team 1 picks in team 2's spot
    assert draft.rosters() == {1: [10, 20], 2: []}
    assert draft.on_clock == 2 and draft.next_pick == 3
    with pytest.raises(DraftError, match="already"):
        draft.add(10)
    assert draft.undo() == (1, 20) and draft.rosters() == {1: [10], 2: []}
    draft.add(30)
    draft.add(40)
    draft.add(50)
    with pytest.raises(DraftError, match="over"):
        draft.add(60)
    assert draft.on_clock is None and Draft.from_dict(draft.to_dict()) == draft


def test_next_pick_of_a_team():
    draft = Draft(Order((1, 2, 3), rounds=2))
    assert draft.next_pick_of(3) == 3
    assert draft.next_pick_of(3, after=4) == 4  # the snake turn
    draft.add(1)
    draft.add(2)
    draft.add(3)
    draft.add(4)
    assert draft.next_pick_of(3) is None


NAMES = {1: "Nikola Jokić", 2: "Jalen Johnson", 3: "Jalen Brunson", 4: "Keldon Johnson",
         5: "Jaren Jackson Jr.", 6: "Shai Gilgeous-Alexander"}  # fmt: skip


def test_typing_a_few_letters_finds_the_player():
    assert normalize("Nikola Jokić") == "nikola jokic"
    assert matches("jok", NAMES)[0] == 1
    assert matches("jokci", NAMES)[0] == 1  # a typo
    assert matches("johnson", NAMES)[:2] == [2, 4]
    assert matches("gilgeous", NAMES) == [6]
    assert matches("jalen b", NAMES) == [3]
    assert matches("", NAMES) == []


def test_pasted_picks_come_back_in_order_once_each():
    text = """R1, P1 Shai Gilgeous-Alexander OKC PG - Team A
    R1, P2 Jalen Johnson ATL SF - Team B
    1.3 Nikola Jokic (DEN)
    Jalen Johnson again"""
    assert parse_paste(text, NAMES) == [6, 2, 1]


# --- A small synthetic pool -------------------------------------------------------------------

SLOTS = {"G": 1, "F": 1, "C": 1, "UT": 1}
POS = ["PG", "SG", "SF", "PF", "C"]


def raw_pool(n=24, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        pos = POS[i % 5]
        slots = {"PG": "G,UT", "SG": "G,UT", "SF": "F,UT", "PF": "F,UT", "C": "C,UT"}[pos]
        rows.append(
            {
                "player_id": 100 + i,
                "player_name": f"P{i}",
                "pro_team": ["AAA", "BBB"][i % 2],
                "position": pos,
                "eligible_slots": slots,
                "injury_status": "ACTIVE",
                "adp": float(i + 1),
                "rank": float(i + 1),
                "rank_roto": float(30 if i == 1 else i + 1),  # 101 slides in categories
                "proj_fpg": float(50 - 1.5 * i + rng.normal(0, 0.5)),
                "proj_games": 70.0,
                "history_games": 70.0,
            }
        )
    return pd.DataFrame(rows)


class SumFormat(DraftFormat):
    """A toy format: strength = the sum of a hidden per-player number, wins = how many
    teams you're stronger than. pick_value can be set to mislead on purpose."""

    def __init__(self, true_value, pick_value=None):
        self._true = np.append(np.asarray(true_value, float), 0.0)
        self._pick = np.asarray(true_value if pick_value is None else pick_value, float)

    @property
    def pick_value(self):
        return self._pick

    def strength(self, rosters):
        return self._true[np.asarray(rosters)].sum(axis=-1)

    def expected_wins(self, s):
        return (s[..., :, None] > s[..., None, :]).sum(axis=-1).astype(float)


NO_SLOTS = {"UT": 4}  # no slot needs any position: no must-fill rule


def small(n=24, teams=(1, 2, 3, 4), rounds=4, true=None, pick=None, slots=SLOTS):
    pool = dpool.build(raw_pool(n), slots)
    true = pool.frame["proj_fpg"].to_numpy() if true is None else true
    return pool, Draft(Order(tuple(teams), rounds)), SumFormat(true, pick)


# --- The pool --------------------------------------------------------------------------------


def test_board_follows_adp_until_it_flattens_then_espns_rank():
    # Like ESPN's: ADP 1-10 for the top 10, then 30 players bunched near 140 whose
    # order only ESPN's rank knows, then one with no ADP at all.
    rng = np.random.default_rng(0)
    deep_rank = rng.permutation(np.arange(11.0, 41.0))
    adp = pd.Series([*np.arange(1.0, 11.0), *(140 + rng.uniform(-0.5, 0.5, 30)), 0.0])
    rank = pd.Series([*np.arange(1.0, 11.0), *deep_rank, 41.0])
    keys = dpool.board_keys(adp, rank, weight=0.0)
    order = list(keys.sort_values().index)
    assert order[:10] == list(range(10))
    assert [rank[i] for i in order[10:40]] == sorted(deep_rank)  # by rank, not by noisy ADP
    assert order[-1] == 40


def test_without_a_plateau_every_adp_counts_and_the_rank_is_blended_in():
    blended = dpool.board_keys(pd.Series([1.0, 2.0]), pd.Series([9.0, 1.0]), weight=0.25)
    assert list(blended) == [0.75 * 1 + 0.25 * 9, 0.75 * 2 + 0.25 * 1]
    keys = dpool.board_keys(pd.Series([1.0, 2.0, 140.0, 141.0]), pd.Series([1.0, 2, 4, 3]), 0.0)
    assert list(keys) == [1.0, 2.0, 140.0, 141.0]  # two high ADPs aren't a plateau


def test_the_format_picks_which_espn_rank_the_board_blends():
    by_points = dpool.build(raw_pool(), SLOTS, "rank").frame["player_id"].tolist()
    by_cats = dpool.build(raw_pool(), SLOTS, "rank_roto").frame["player_id"].tolist()
    assert by_points[:3] == [100, 101, 102]
    assert by_cats.index(101) > by_points.index(101) + 3


@pytest.mark.parametrize(
    "risk,expected",
    [("ignore", [75, 75, 70]), ("neutral", [55, 75, 70]), ("avoid", [46.75, 75, 59.5])],
)
def test_projected_games_by_risk(risk, expected):
    proj = pd.Series([75.0, 75.0, 70.0])
    history = pd.Series([55.0, np.nan, 80.0])  # misses a lot / a rookie / healthy but OUT now
    injured = pd.Series([False, False, True])
    assert list(dpool.projected_games(proj, history, injured, risk)) == pytest.approx(expected)


# --- Simulations ------------------------------------------------------------------------------


def test_without_noise_managers_take_the_board_in_order():
    pool, draft, fmt = small(slots=NO_SLOTS)
    runs = simulate.simulate(draft, pool, fmt, EXACT, None, runs=3,
                             watch=range(1, draft.order.total + 1))  # fmt: skip
    taken = [int(runs.choices[k][0]) for k in range(1, draft.order.total + 1)]
    assert taken == list(range(draft.order.total))  # pool is sorted by key


def test_you_draft_by_value_and_the_forced_pick_is_taken_when_there():
    pool, draft, fmt = small(pick=np.arange(24.0), slots=NO_SLOTS)  # value: worst first
    runs = simulate.simulate(draft, pool, fmt, EXACT, me=1, runs=2, force=5, force_pick=1)
    assert sorted(runs.rosters[0, 0].tolist()) == [5, 21, 22, 23]


def test_teams_fill_empty_starting_slots_before_their_picks_run_out():
    pool, draft, fmt = small()  # G, F and C to fill in 4 rounds
    runs = simulate.simulate(draft, pool, fmt, EXACT, None, runs=2)
    covered = pool.eligible[runs.rosters[0]].sum(axis=1)  # (teams, slot types)
    assert (covered >= pool.slot_counts).all()


def test_same_seed_same_runs_and_only_your_choice_differs():
    pool, draft, fmt = small()
    model = OpponentModel(3.0, 0.2, 0.5)
    a = simulate.simulate(draft, pool, fmt, model, 1, runs=50, seed=4)
    b = simulate.simulate(draft, pool, fmt, model, 1, runs=50, seed=4)
    assert (a.rosters == b.rosters).all()
    c = simulate.simulate(draft, pool, fmt, model, 1, runs=50, seed=5)
    assert (a.rosters != c.rosters).any()


def test_roster_rules_cap_a_position_and_fill_empty_slots():
    pool, _, fmt = small(n=40)
    draft = Draft(Order((1, 2, 3, 4), rounds=6))
    model = OpponentModel(3.0, 0.2, cap_share=0.34)  # at most 3 at one position
    runs = simulate.simulate(draft, pool, fmt, model, None, runs=40)
    position = pool.position
    eligible = pool.eligible
    for r in range(40):
        for t in range(4):
            roster = runs.rosters[r, t]
            assert np.bincount(position[roster], minlength=5).max() <= 3
            assert (eligible[roster].sum(axis=0) >= pool.slot_counts).all()  # G, F, C covered


def test_existing_picks_are_kept_and_unknown_players_hold_a_spot():
    pool, draft, fmt = small()
    draft.add(103)
    draft.add(999)  # not in the pool
    runs = simulate.simulate(draft, pool, fmt, EXACT, 1, runs=2)
    assert runs.rosters[0, 0, 0] == 3 and runs.rosters[0, 1, 0] == -1
    assert (runs.rosters >= -1).all() and (runs.rosters[:, :, -1] != -1).all()


# --- Recommendations -----------------------------------------------------------------------------


def final_wins_by_hand(pool, draft, fmt, me, first):
    """Without noise every run is the same draft: play it by hand."""
    state = Draft(draft.order, list(draft.picks))
    taken = set()
    board = list(range(len(pool.frame)))
    value = fmt.pick_value
    rosters = {t: [] for t in draft.order.teams}
    for k in range(draft.next_pick, draft.order.total + 1):
        team = draft.order.owner(k)
        left = [i for i in board if i not in taken]
        if team == me:
            choice = first if k == draft.next_pick_of(me) else max(left, key=lambda i: value[i])
        else:
            choice = left[0]
        taken.add(choice)
        rosters[team].append(choice)
    arr = np.array([[rosters[t] for t in state.order.teams]])
    return fmt.expected_wins(fmt.strength(arr))[0][list(state.order.teams).index(me)]


def test_scores_are_exactly_the_hand_played_drafts():
    pool, draft, fmt = small(slots=NO_SLOTS)
    advice = recommend.recommend(draft, pool, fmt, EXACT, me=2, runs=3, top=10)
    for row in advice.picks.itertuples():
        assert row.wins == pytest.approx(final_wins_by_hand(pool, draft, fmt, 2, row.index))


def test_picks_follow_expected_wins_not_the_value_column():
    # The value column ranks the best player last; expected wins still take him first.
    pool, _, _ = small()
    true = pool.frame["proj_fpg"].to_numpy()
    misleading = true.copy()
    misleading[0] = -100.0
    pool, draft, fmt = small(true=true, pick=misleading, slots=NO_SLOTS)
    advice = recommend.recommend(draft, pool, fmt, EXACT, me=1, runs=3, top=3, shortlist=24)
    assert advice.picks.iloc[0]["index"] == 0
    assert advice.picks.iloc[0]["wins"] > advice.picks.iloc[1]["wins"]
    assert advice.on_clock and advice.pick == 1


def test_a_player_likely_gone_scores_as_your_fallback():
    pool, draft, fmt = small()
    # Team 4 picks 4th; players 0-2 are always gone by then without noise.
    advice = recommend.recommend(draft, pool, fmt, EXACT, me=4, runs=3, top=24, shortlist=24)
    gone = advice.picks.loc[advice.picks["index"] < 3]
    assert gone.empty  # never there: not even considered
    assert (advice.picks["there"] == 1).all()


def test_league_table_ranks_every_team():
    pool, draft, fmt = small()
    advice = recommend.recommend(draft, pool, fmt, OpponentModel(), me=1, runs=40)
    league = advice.league
    assert set(league["team_id"]) == {1, 2, 3, 4}
    assert league["wins"].sum() == pytest.approx(6.0)  # 4 teams: 6 pairings, one win each
    assert (league["strength_now"] == 0).all()
    assert league["first"].sum() >= 1 - 1e-9  # someone finishes first in every run


def test_the_engine_knows_nothing_about_formats():
    """state, pool, simulate, recommend and calibrate import no format's math."""
    root = pathlib.Path(__file__).resolve().parents[2] / "app" / "draft"
    for name in ("state", "pool", "simulate", "recommend", "calibrate"):
        tree = ast.parse((root / f"{name}.py").read_text())
        imported = {
            node.module if isinstance(node, ast.ImportFrom) else alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in getattr(node, "names", [])
        }
        assert not any(m and (m.startswith("points") or m.startswith("analysis")) for m in imported)


# --- The points format -------------------------------------------------------------------------


def test_points_strength_is_the_points_engines_fast_estimate():
    rng = np.random.default_rng(1)
    fpg, games = rng.uniform(10, 50, 12), rng.uniform(2, 4, 12)
    fmt = PointsFormat(fpg, games, 6.5, 5, fpg)
    rosters = np.array([[[0, 1, 2, 3, 4, 5, -1], [6, 7, 8, 9, 10, 11, -1]]])
    s = fmt.strength(rosters)
    assert s[0, 0] == pytest.approx(points_model.fast_weekly_points(fpg[:6], games[:6], 6.5, 5))
    wins = fmt.expected_wins(s)
    assert wins.sum() == pytest.approx(1.0)  # two teams: one win between them
    four = fmt.expected_wins(np.array([[100.0, 120.0, 90.0, 110.0]]))
    assert four.sum() == pytest.approx(6.0) and four[0].argmax() == 1


# --- Calibration --------------------------------------------------------------------------------


def test_a_model_replaying_its_own_draft_predicts_it_perfectly():
    pool, draft, fmt = small(n=30)
    real = simulate.simulate(draft, pool, fmt, EXACT, None, runs=1,
                             watch=range(1, draft.order.total + 1))  # fmt: skip
    picks = [(draft.order.owner(k), int(pool.ids[real.choices[k][0]]))
             for k in range(1, draft.order.total + 1)]  # fmt: skip
    check = calibrate.availability_check(draft.order, picks, pool, fmt, EXACT, every=2,
                                         ahead=3, runs=2)  # fmt: skip
    assert calibrate.brier(check) == 0.0
    assert set(check["predicted"]) <= {0.0, 1.0}


def test_noise_is_fitted_to_how_far_picks_stray():
    pool, draft, fmt = small(n=40)
    truth = OpponentModel(0.0, 0.3, 1.0)
    real = simulate.simulate(Draft(Order((1, 2, 3, 4), 6)), pool, fmt, truth, None, runs=1,
                             seed=11, watch=range(1, 25))  # fmt: skip
    picks = [(Order((1, 2, 3, 4), 6).owner(k), int(pool.ids[real.choices[k][0]]))
             for k in range(1, 25)]  # fmt: skip
    model, grid = calibrate.fit([(Order((1, 2, 3, 4), 6), picks, pool, fmt)], runs=40, every=4)
    assert model.noise_share > 0  # a noisy draft isn't fitted as a noiseless one
    assert list(grid["brier"]) == sorted(grid["brier"])
    most = calibrate.position_cap_share(picks, pool, 6) * 6
    assert math.isclose(model.cap(6), max(2, round(most)))


# --- ESPN's picks and the live draft's storage --------------------------------------------------


def test_espns_picks_replace_entered_ones_and_later_entries_stay():
    draft = Draft(Order((1, 2), rounds=3))
    for player in (10, 99, 30, 40):  # pick 2 was entered wrong (99)
        draft.add(player)
    merged = merge_official(draft, [(2, 2, 20), (1, 1, 10)])
    assert merged.picks == [(1, 10), (2, 20), (2, 30), (1, 40)]
    assert merge_official(draft, []).picks == draft.picks
    again = merge_official(draft, [(1, 1, 10), (2, 2, 30)])  # ESPN has 30 at pick 2
    assert again.picks == [(1, 10), (2, 30), (1, 40)]


def test_a_live_draft_survives_a_reload():
    db = FakeFirestore()
    draft = Draft(Order((4, 7), rounds=2))
    draft.add(11)
    now = dt.datetime(2026, 10, 7, tzinfo=dt.UTC)
    store.save(db, 5, 2027, draft, "u-ana", now)
    assert store.load(db, 5, 2027) == draft
    assert store.load(db, 5, 2026) is None
    store.clear(db, 5, 2027)
    assert store.load(db, 5, 2027) is None
