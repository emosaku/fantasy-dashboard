"""Trade simulation and the trade finder.

simulate_trade applies one deal to the team totals and reports both sides' change
in E per category. find_trades searches every 1-for-1 and 2-for-1 deal (both
directions) with every other team, vectorized over team-total arrays -- a deal only
changes two teams' rows -- and keeps the win-win ones. The Mock trade tab runs
simulate_trade on the same inputs, so a loaded deal shows the same numbers.
deals_for_target builds the same deals around one player I want (2-for-2 included)
and sorts them by how likely the other manager is to accept.

Roster size stays even on both sides. The side receiving two players for one drops
its lowest-valued remaining player (by its own weights), never one it just received.
The side giving two for one is left a player short, so it picks up the best
available free agent by its own weights -- what a real manager would do with the
open slot. Without that, every 2-for-1 looked like a free upgrade for whoever got
two players. IR players are left out of the search: they add nothing while on IR.
"""

import math
from dataclasses import dataclass
from itertools import combinations

import numpy as np
import pandas as pd

from analysis.objective import category_wins, head_to_head
from analysis.pool import contribution
from analysis.weights import generic_values, player_values, punts
from categories import COLUMNS

LOPSIDED_GAP = 1.5  # generic value given vs received, in total z


@dataclass
class SideResult:
    team_id: int | None
    cat_delta: pd.Series  # change in category wins per category, punts zeroed
    delta_e: float


def _side_delta(before: pd.DataFrame, after: pd.DataFrame, team_id: int, punted) -> SideResult:
    def wins(totals):
        row = totals.loc[team_id].to_numpy()
        return category_wins(row, totals.drop(team_id).to_numpy())

    delta = pd.Series(wins(after) - wins(before), index=COLUMNS)
    delta[list(punted)] = 0.0
    return SideResult(team_id, delta, float(delta.sum()))


def present(player_id) -> bool:
    """A drop slot can hold None, or NaN once it has been through a DataFrame."""
    return player_id is not None and not pd.isna(player_id)


def as_ids(players) -> list:
    """A roster move as a list of player ids: None/NaN (nobody), one id, or several."""
    if players is None or isinstance(players, (int, float, np.integer, np.floating)):
        return [players] if present(players) else []
    return [p for p in players if present(p)]


def best_pickup(players: pd.DataFrame, weights: pd.DataFrame):
    """The free agent (not OUT) worth the most to a team, or None."""
    pool = players.loc[players["is_free_agent"] & (players["injury_status"] != "OUT")]
    if pool.empty:
        return None
    return player_values(pool, weights).idxmax()


def apply_trade(
    players: pd.DataFrame,
    totals: pd.DataFrame,
    me: int,
    them: int | None,
    give=(),
    get=(),
    my_drop=None,
    their_drop=None,
    my_add=None,
    their_add=None,
    empty=None,
) -> pd.DataFrame:
    """Team totals after a deal. them=None means the free-agent pool (a waiver move:
    `give` are drops, `get` are pickups); only my row changes then. *_drop / *_add
    are the add/drop moves that go with the deal: each one player id, None, or a list
    of ids (my side can add and drop several free agents around a trade).
    empty: the z of an empty roster spot (pool.empty_slot_z). Given, a side left with
    fewer players than it started with is charged an empty spot for each one short --
    otherwise an open spot counts as an average player."""

    def moved(ids_out, ids_in, drop, add):
        ins, outs = [*ids_in, *as_ids(add)], [*ids_out, *as_ids(drop)]
        delta = contribution(players, ins) - contribution(players, outs)
        short = len(outs) - len(ins)
        if empty is not None and short > 0:
            delta = delta + short * empty.reindex(totals.columns).fillna(0).to_numpy()
        return delta

    after = totals.copy()
    after.loc[me] = after.loc[me].to_numpy() + moved(give, get, my_drop, my_add)
    if them is not None:
        after.loc[them] = after.loc[them].to_numpy() + moved(get, give, their_drop, their_add)
    return after


def simulate_trade(
    players,
    totals,
    me,
    them,
    give=(),
    get=(),
    my_drop=None,
    their_drop=None,
    my_add=None,
    their_add=None,
    punts_me=(),
    punts_them=(),
    empty=None,
) -> tuple[pd.DataFrame, SideResult, SideResult | None]:
    """(totals after, my result, their result or None for a free-agent move)."""
    after = apply_trade(
        players, totals, me, them, give, get, my_drop, their_drop, my_add, their_add, empty
    )
    mine = _side_delta(totals, after, me, punts_me)
    theirs = None if them is None else _side_delta(totals, after, them, punts_them)
    return after, mine, theirs


def _lowest(values: np.ndarray, excluded: np.ndarray) -> np.ndarray:
    """For each row of `excluded` (k x m booleans), the index of the lowest value
    not excluded."""
    masked = np.where(excluded, np.inf, values[None, :])
    return masked.argmin(axis=1)


def _deals_with(players, totals, me, them, weights_me, weights_them, target=None):
    """Every 1-for-1 and 2-for-1 deal with one partner, as arrays. With a `target`
    (one of their players): only deals that bring him to me, 2-for-2 included."""
    mine = players.loc[(players["team_id"] == me) & ~players["is_ir"]]
    theirs = players.loc[(players["team_id"] == them) & ~players["is_ir"]]
    if mine.empty or theirs.empty:
        return []
    za, zb = mine[COLUMNS].to_numpy(), theirs[COLUMNS].to_numpy()
    va = player_values(mine, weights_me).to_numpy()
    vb = player_values(theirs, weights_them).to_numpy()
    ida, idb = mine.index.to_numpy(), theirs.index.to_numpy()
    na, nb = len(ida), len(idb)
    my_pick, their_pick = best_pickup(players, weights_me), best_pickup(players, weights_them)
    z_my_pick = players.loc[my_pick, COLUMNS].to_numpy(float) if my_pick is not None else 0
    z_their_pick = players.loc[their_pick, COLUMNS].to_numpy(float) if their_pick is not None else 0

    if target is not None:
        if target not in set(idb):
            return []
        shapes = _target_shapes(int(np.flatnonzero(idb == target)[0]), na, nb, va, vb)
        return _evaluate(shapes, za, zb, ida, idb, totals, me, them, my_pick, their_pick,
                         z_my_pick, z_their_pick)  # fmt: skip

    shapes = []  # (give index tuples, get index tuples, my_drop idx|-1, their_drop idx|-1)
    for i in range(na):
        for j in range(nb):
            shapes.append(((i,), (j,), -1, -1))
    for i1, i2 in combinations(range(na), 2):  # I give two, they drop one
        for j in range(nb):
            if nb > 1:
                excluded = np.zeros(nb, bool)
                excluded[j] = True
                shapes.append(((i1, i2), (j,), -1, int(_lowest(vb, excluded[None])[0])))
    for i in range(na):  # I get two, I drop one
        for j1, j2 in combinations(range(nb), 2):
            if na > 1:
                excluded = np.zeros(na, bool)
                excluded[i] = True
                shapes.append(((i,), (j1, j2), int(_lowest(va, excluded[None])[0]), -1))
    return _evaluate(
        shapes, za, zb, ida, idb, totals, me, them, my_pick, their_pick, z_my_pick, z_their_pick
    )


def _target_shapes(j0: int, na: int, nb: int, va, vb) -> list:
    """Deals that bring their player j0 to me: 1-for-1, 2-for-1 (they drop their
    least useful other player), 1-for-2 (j0 plus one more; I drop my least useful
    remaining player) and 2-for-2 (rosters stay even, nobody drops)."""
    shapes = [((i,), (j0,), -1, -1) for i in range(na)]
    if nb > 1:
        excluded = np.zeros(nb, bool)
        excluded[j0] = True
        their_drop = int(_lowest(vb, excluded[None])[0])
        shapes += [((i1, i2), (j0,), -1, their_drop) for i1, i2 in combinations(range(na), 2)]
    others = [j for j in range(nb) if j != j0]
    if na > 1:
        for i in range(na):
            excluded = np.zeros(na, bool)
            excluded[i] = True
            my_drop = int(_lowest(va, excluded[None])[0])
            shapes += [((i,), (j0, j), my_drop, -1) for j in others]
    shapes += [((i1, i2), (j0, j), -1, -1) for i1, i2 in combinations(range(na), 2) for j in others]
    return shapes


def _evaluate(shapes, za, zb, ida, idb, totals, me, them, my_pick, their_pick, z_my_pick,
              z_their_pick):  # fmt: skip
    """Both teams' totals after each deal shape, and the deals as player ids."""
    my_new = np.empty((len(shapes), len(COLUMNS)))
    their_new = np.empty_like(my_new)
    t_me, t_them = totals.loc[me].to_numpy(), totals.loc[them].to_numpy()
    for k, (gi, gj, md, td) in enumerate(shapes):
        sent, received = za[list(gi)].sum(0), zb[list(gj)].sum(0)
        # Short a player (gave two, got one) -> fill the slot from free agents.
        my_fill = z_my_pick if len(gi) > len(gj) else 0
        their_fill = z_their_pick if len(gj) > len(gi) else 0
        my_new[k] = t_me - sent + received - (za[md] if md >= 0 else 0) + my_fill
        their_new[k] = t_them - received + sent - (zb[td] if td >= 0 else 0) + their_fill
    ids = [
        (
            tuple(ida[list(gi)]),
            tuple(idb[list(gj)]),
            ida[md] if md >= 0 else None,
            idb[td] if td >= 0 else None,
            my_pick if len(gi) > len(gj) else None,
            their_pick if len(gj) > len(gi) else None,
        )
        for gi, gj, md, td in shapes
    ]
    return ids, my_new, their_new


def find_trades(
    players: pd.DataFrame,
    totals: pd.DataFrame,
    me: int,
    weights_by_team: dict,
    top: int = 15,
) -> pd.DataFrame:
    """Win-win deals for `me`: my E goes up and the partner's doesn't go down.
    Ranked by my change in E, then theirs."""
    generic = generic_values(
        players
    ).to_dict()  # plain dict: O(1) lookups beat repeated Series indexing
    rows = []
    for them in totals.index:
        if them == me:
            continue
        found = _deals_with(players, totals, me, them, weights_by_team[me], weights_by_team[them])
        if not found:
            continue
        ids, my_new, their_new = found
        my_cat, their_cat = _category_changes(
            totals, me, them, my_new, their_new, weights_by_team[me], weights_by_team[them]
        )
        d_me, d_them = my_cat.sum(1), their_cat.sum(1)

        keep = np.flatnonzero((d_me > 1e-9) & (d_them > -1e-9))
        for k in keep:
            give, get, my_drop, their_drop, my_add, their_add = ids[k]
            gen_give, gen_get = sum(generic[p] for p in give), sum(generic[p] for p in get)
            rows.append(
                {
                    "partner_id": them,
                    "give_ids": give,
                    "get_ids": get,
                    "my_drop_id": my_drop,
                    "their_drop_id": their_drop,
                    "my_add_id": my_add,
                    "their_add_id": their_add,
                    "dE_me": d_me[k],
                    "dE_them": d_them[k],
                    "gen_give": gen_give,
                    "gen_get": gen_get,
                    "lopsided": abs(gen_give - gen_get) > LOPSIDED_GAP,
                    **{f"dE_{c}": my_cat[k, i] for i, c in enumerate(COLUMNS)},
                }
            )
    if not rows:
        return pd.DataFrame()
    deals = pd.DataFrame(rows).sort_values(["dE_me", "dE_them"], ascending=False)
    return deals.head(top).reset_index(drop=True)


def _category_changes(totals, me, them, my_new, their_new, weights_me, weights_them):
    """Each deal's change in category wins per category, for me and for them (each
    side's punted categories zeroed). Only the two teams' rows change."""
    fixed = totals.drop([me, them]).to_numpy()
    base_me = category_wins(totals.loc[me].to_numpy(), totals.drop(me).to_numpy())
    base_them = category_wins(totals.loc[them].to_numpy(), totals.drop(them).to_numpy())
    my_cat = category_wins(my_new, fixed) + head_to_head(my_new, their_new) - base_me
    their_cat = category_wins(their_new, fixed) + head_to_head(their_new, my_new) - base_them
    my_cat[:, np.isin(COLUMNS, punts(weights_me))] = 0.0
    their_cat[:, np.isin(COLUMNS, punts(weights_them))] = 0.0
    return my_cat, their_cat


# How likely the other manager is to accept a deal for a target, best first.
LIKELY, COSTS_YOU, THEY_SAY_NO = "likely", "costs_you", "they_say_no"
STATUS_ORDER = {LIKELY: 0, COSTS_YOU: 1, THEY_SAY_NO: 2}


def deals_for_target(
    players: pd.DataFrame, totals: pd.DataFrame, me: int, target, weights_by_team: dict
) -> pd.DataFrame:
    """Every 1-for-1, 2-for-1, 1-for-2 and 2-for-2 deal that brings `target` (a player
    on another roster) to me, with a status:

      likely       -- I gain category wins, they don't lose any, and the general value
                      I get isn't more than LOPSIDED_GAP above what I give;
      costs_you    -- they'd accept on the same tests, but I don't gain: the price of
                      the player;
      they_say_no  -- I gain, but they lose category wins or the deal is lopsided in
                      my favor.

    Deals that neither side gains from are left out. Sorted by status; within
    `likely` by my gain, then the least general value given up (keep your best
    players); `costs_you` by my change (cheapest first); `they_say_no` by how close
    they come to accepting."""
    them = int(players.at[target, "team_id"])
    found = _deals_with(
        players, totals, me, them, weights_by_team[me], weights_by_team[them], target=target
    )
    if not found:
        return pd.DataFrame()
    ids, my_new, their_new = found
    my_cat, their_cat = _category_changes(
        totals, me, them, my_new, their_new, weights_by_team[me], weights_by_team[them]
    )
    d_me, d_them = my_cat.sum(1), their_cat.sum(1)
    generic = generic_values(
        players
    ).to_dict()  # plain dict: O(1) lookups beat repeated Series indexing
    rows = []
    for k, (give, get, my_drop, their_drop, my_add, their_add) in enumerate(ids):
        gen_give, gen_get = sum(generic[p] for p in give), sum(generic[p] for p in get)
        fair = gen_get - gen_give <= LOPSIDED_GAP
        accepts = d_them[k] > -1e-9 and fair
        gains = d_me[k] > 1e-9
        if gains and accepts:
            status = LIKELY
        elif accepts:
            status = COSTS_YOU
        elif gains:
            status = THEY_SAY_NO
        else:
            continue
        rows.append(
            {
                "status": status,
                "partner_id": them,
                "give_ids": give,
                "get_ids": get,
                "my_drop_id": my_drop,
                "their_drop_id": their_drop,
                "my_add_id": my_add,
                "their_add_id": their_add,
                "dE_me": d_me[k],
                "dE_them": d_them[k],
                "gen_give": gen_give,
                "gen_get": gen_get,
                "lopsided": abs(gen_give - gen_get) > LOPSIDED_GAP,
                **{f"dE_{c}": my_cat[k, i] for i, c in enumerate(COLUMNS)},
            }
        )
    if not rows:
        return pd.DataFrame()
    deals = pd.DataFrame(rows)
    order = deals["status"].map(STATUS_ORDER)
    # One sort key per status, so each group is ordered by what matters for it.
    key = np.where(
        deals["status"] == THEY_SAY_NO, -deals["dE_them"] * 100 - deals["dE_me"], -deals["dE_me"]
    )
    deals = deals.assign(_order=order, _key=key).sort_values(["_order", "_key", "gen_give"])
    return deals.drop(columns=["_order", "_key"]).reset_index(drop=True)


def top_targets(players, me, weights_me, n=10) -> pd.DataFrame:
    """Players on other rosters worth the most to me."""
    others = players.loc[
        players["team_id"].notna() & (players["team_id"] != me) & ~players["is_ir"]
    ]
    return (
        others.assign(value=player_values(others, weights_me), generic=generic_values(others))
        .sort_values("value", ascending=False)
        .head(n)
    )


def trade_chips(players, me, weights_me, n=5) -> pd.DataFrame:
    """My players worth much less to me than in general: their value sits in
    categories I've locked or punted, so they're worth more to someone else."""
    mine = players.loc[(players["team_id"] == me) & ~players["is_ir"]]
    return (
        mine.assign(value=player_values(mine, weights_me), generic=generic_values(mine))
        .assign(surplus=lambda d: d["generic"] - d["value"])
        .sort_values("surplus", ascending=False)
        .head(n)
    )


# --- Offer Builder: search from a trade block, not the whole roster ----------------
#
# The Trade finder and Create a Trade search your WHOLE roster against one shape at a
# time (1-for-1, 2-for-1, and -- for one target player -- 1-for-2/2-for-2). Offer
# Builder answers a different question: "I'll move these specific guys -- what's the
# best I can get, from whom?" That needs its own enumeration (a restricted give side,
# sizes up to 3 either way, an even-sizes-only mode, and an injury filter on the get
# side), so it gets its own search function, _offers_with, rather than forcing those
# cases into _deals_with's fixed shapes. It reuses everything else: _category_changes
# for scoring, generic_values and LOPSIDED_GAP for fairness, and the same "drop your
# lowest / add the best free agent" balancing rule, generalized to more than one
# player when a deal is uneven by more than one (a 3-for-1, for instance).

WIN_WIN, CLOSE_CALL, MAX_GAIN = "win_win", "close_call", "max_gain"
CLOSE_CALL_FLOOR = -2.0  # ΔE_them floor for "close call"
MAX_SEARCH_DEALS = 250_000
OFFERS_PER_TEAM_CAP = 3


class SearchTooLarge(Exception):
    """The search as configured would enumerate more than MAX_SEARCH_DEALS deals;
    the message is for people."""


def _combo_counts(n: int, max_size: int) -> dict[int, int]:
    return {s: math.comb(n, s) for s in range(1, min(max_size, n) + 1)}


def offer_search_size(
    block_size: int, roster_sizes: list[int], max_give: int, max_get: int, allow_uneven: bool
) -> int:
    """How many deals a search would enumerate, before building any of them -- cheap
    combinatorics, so the 250,000 guard can run first."""
    give_counts = _combo_counts(block_size, max_give)
    total = 0
    for roster_size in roster_sizes:
        get_counts = _combo_counts(roster_size, max_get)
        if allow_uneven:
            total += sum(give_counts.values()) * sum(get_counts.values())
        else:
            for size in range(1, min(max_give, max_get) + 1):
                total += give_counts.get(size, 0) * get_counts.get(size, 0)
    return total


def _subset_shapes(n: int, max_size: int) -> list[tuple[int, ...]]:
    """Every non-empty index combo of size 1..max_size out of range(n)."""
    shapes = []
    for size in range(1, min(max_size, n) + 1):
        shapes.extend(combinations(range(n), size))
    return shapes


def _k_lowest_cumsum(z: np.ndarray, values: np.ndarray, max_k: int):
    """Ascending by `values`: the ids' sort order, and the cumulative sum of the k
    lowest rows of `z` for k=1..max_k, as a (max_k, z.shape[1]) array (row k-1 = the
    sum of the k lowest). Holds at the last sum if there are fewer than max_k rows."""
    order = np.argsort(values)
    k = min(max_k, len(order))
    out = np.zeros((max(max_k, 1), z.shape[1]))
    if k:
        out[:k] = np.cumsum(z[order[:k]], axis=0)
        out[k:] = out[k - 1]
    return out, order


def _offers_with(
    players: pd.DataFrame,
    totals: pd.DataFrame,
    me: int,
    them: int,
    block: list,
    weights_me: pd.DataFrame,
    weights_them: pd.DataFrame,
    max_give: int,
    max_get: int,
    allow_uneven: bool,
    exclude_injured: bool,
):
    """Every deal of the requested sizes between `block` (mine, a subset of my
    roster) and team `them`'s roster, balanced like _deals_with: whichever side ends
    up with more players than it started drops its lowest-value remaining ones (by
    its own weights, never one just traded away); the other side picks up that many
    of the best available free agents (by its own weights). Unlike _deals_with, this
    isn't limited to being short by one -- a 3-for-1 deal is short by two."""
    mine_full = players.loc[(players["team_id"] == me) & ~players["is_ir"]]
    block_rows = mine_full.loc[mine_full.index.isin(block)]
    theirs_full = players.loc[(players["team_id"] == them) & ~players["is_ir"]]
    theirs = theirs_full
    if exclude_injured:
        theirs = theirs.loc[theirs["injury_status"] != "OUT"]
    if block_rows.empty or theirs.empty:
        return []

    za, zb = block_rows[COLUMNS].to_numpy(), theirs[COLUMNS].to_numpy()
    ida, idb = block_rows.index.to_numpy(), theirs.index.to_numpy()
    za_full, ida_full = mine_full[COLUMNS].to_numpy(), mine_full.index.to_numpy()
    zb_full, idb_full = theirs_full[COLUMNS].to_numpy(), theirs_full.index.to_numpy()
    va_full = player_values(mine_full, weights_me).to_numpy()
    vb_full = player_values(theirs_full, weights_them).to_numpy()

    max_k = max(max_give, max_get) - 1  # most a side is ever short or over by

    fa_pool = players.loc[players["is_free_agent"] & (players["injury_status"] != "OUT")]
    fa_z = fa_pool[COLUMNS].to_numpy()
    fa_ids = fa_pool.index.to_numpy()

    def best_free_agents(weights):
        order = (-player_values(fa_pool, weights).to_numpy()).argsort()
        cumz, _ = _k_lowest_cumsum(fa_z[order], np.arange(len(order)), max_k)
        return cumz, fa_ids[order][:max_k]

    my_add_cumz, my_add_ids_sorted = best_free_agents(weights_me)
    their_add_cumz, their_add_ids_sorted = best_free_agents(weights_them)

    give_shapes = _subset_shapes(len(ida), max_give)
    get_shapes = _subset_shapes(len(idb), max_get)
    if not allow_uneven:
        max_pair = min(max_give, max_get)
        give_shapes = [g for g in give_shapes if len(g) <= max_pair]
        get_shapes = [g for g in get_shapes if len(g) <= max_pair]

    give_drop_cache = {}
    for gi in give_shapes:
        mask = ~np.isin(ida_full, ida[list(gi)])
        cumz, order = _k_lowest_cumsum(za_full[mask], va_full[mask], max_k)
        give_drop_cache[gi] = (cumz, ida_full[mask][order][:max_k])

    get_drop_cache = {}
    for gj in get_shapes:
        mask = ~np.isin(idb_full, idb[list(gj)])
        cumz, order = _k_lowest_cumsum(zb_full[mask], vb_full[mask], max_k)
        get_drop_cache[gj] = (cumz, idb_full[mask][order][:max_k])

    zeros = np.zeros(len(COLUMNS))
    t_me, t_them = totals.loc[me].to_numpy(), totals.loc[them].to_numpy()

    # Precomputed once per shape, not once per (give, get) pair: the inner loop below
    # runs up to ~15,000 times per team, and re-summing the same get combo's z-scores
    # on every one of those (instead of once per get combo) was the search's main
    # cost -- about 40x more sums than it needs for the give side's shape count.
    give_sent = {gi: (za[list(gi)].sum(0), tuple(ida[list(gi)])) for gi in give_shapes}
    get_received = {gj: (zb[list(gj)].sum(0), tuple(idb[list(gj)])) for gj in get_shapes}

    ids, my_new_list, their_new_list = [], [], []
    for gi in give_shapes:
        sent, give_ids = give_sent[gi]
        give_cumz, give_drop_ids = give_drop_cache[gi]
        for gj in get_shapes:
            if not allow_uneven and len(gi) != len(gj):
                continue
            received, get_ids = get_received[gj]
            get_cumz, get_drop_ids = get_drop_cache[gj]

            my_drop_ids = their_drop_ids = my_add_ids = their_add_ids = ()
            my_drop_sum = their_drop_sum = my_add_sum = their_add_sum = zeros
            diff = len(gj) - len(gi)  # positive: I received more than I gave
            if diff > 0:
                k = min(diff, len(give_drop_ids))
                my_drop_ids = tuple(give_drop_ids[:k])
                my_drop_sum = give_cumz[k - 1] if k else zeros
                k2 = min(diff, len(their_add_ids_sorted))
                their_add_ids = tuple(their_add_ids_sorted[:k2])
                their_add_sum = their_add_cumz[k2 - 1] if k2 else zeros
            elif diff < 0:
                need = -diff
                k = min(need, len(get_drop_ids))
                their_drop_ids = tuple(get_drop_ids[:k])
                their_drop_sum = get_cumz[k - 1] if k else zeros
                k2 = min(need, len(my_add_ids_sorted))
                my_add_ids = tuple(my_add_ids_sorted[:k2])
                my_add_sum = my_add_cumz[k2 - 1] if k2 else zeros

            my_new_list.append(t_me - sent + received - my_drop_sum + my_add_sum)
            their_new_list.append(t_them - received + sent - their_drop_sum + their_add_sum)
            ids.append((give_ids, get_ids, my_drop_ids, their_drop_ids, my_add_ids, their_add_ids))
    if not ids:
        return []
    return ids, np.array(my_new_list), np.array(their_new_list)


def _drop_dominated(rows: list[dict]) -> list[dict]:
    """Within one partner's deals (same give set): if a get set's gain is no better
    than one of its immediate smaller versions (one fewer player, already in this
    list), the extra player adds nothing -- drop the bigger deal, keep the smaller
    one. Checks only immediate (one-player-smaller) versions, not every subset, which
    is enough to catch the common case (a throw-in that doesn't help) without an
    expensive all-pairs comparison."""
    by_shape = {(row["give_ids"], frozenset(row["get_ids"])): row["dE_me"] for row in rows}
    kept = []
    for row in rows:
        get_set = frozenset(row["get_ids"])
        dominated = len(get_set) > 1 and any(
            by_shape.get((row["give_ids"], get_set - {p}), -np.inf) >= row["dE_me"] - 1e-9
            for p in get_set
        )
        if not dominated:
            kept.append(row)
    return kept


def build_offers(
    players: pd.DataFrame,
    totals: pd.DataFrame,
    me: int,
    block,
    targets: list[int],
    weights_by_team: dict,
    max_give: int = 2,
    max_get: int = 2,
    acceptance: str = WIN_WIN,
    exclude_injured: bool = True,
    allow_uneven: bool = True,
    top: int = 15,
    per_team_cap: int = OFFERS_PER_TEAM_CAP,
    max_search: int = MAX_SEARCH_DEALS,
) -> pd.DataFrame:
    """Every deal built only from `block` (players I'm willing to move) against each
    team in `targets`, that raises my expected category wins (ΔE_me > 0), filtered
    by `acceptance`:

      win_win     -- ΔE_them >= 0 and not Lopsided (the default: offers likely to work)
      close_call  -- ΔE_them >= -2 and not Lopsided (a small cost to them, offset by
                      looking fair on paper)
      max_gain    -- no limit on ΔE_them (the ceiling; most will be rejected)

    Lopsided uses the same rule as the Trade finder: general value given and
    received differ by more than LOPSIDED_GAP. Sorted by my gain, then theirs; near-
    duplicates dropped (see _drop_dominated); at most `per_team_cap` offers from any
    one partner when `targets` has more than one team. Raises SearchTooLarge before
    building anything if the search would check more than MAX_SEARCH_DEALS deals."""
    block = [
        int(p)
        for p in block
        if p in players.index and players.at[p, "team_id"] == me and not players.at[p, "is_ir"]
    ]
    targets = [int(t) for t in targets if t != me]
    if not block or not targets:
        return pd.DataFrame()

    def eligible_roster_size(team_id: int) -> int:
        roster = players.loc[(players["team_id"] == team_id) & ~players["is_ir"]]
        if exclude_injured:
            roster = roster.loc[roster["injury_status"] != "OUT"]
        return len(roster)

    size = offer_search_size(
        len(block), [eligible_roster_size(t) for t in targets], max_give, max_get, allow_uneven
    )
    if size > max_search:
        raise SearchTooLarge(
            f"That search would check {size:,} deals, more than the "
            f"{max_search:,} limit. Pick fewer players for your trade block, "
            "or lower the max sizes."
        )

    generic = generic_values(
        players
    ).to_dict()  # plain dict: O(1) lookups beat repeated Series indexing
    rows = []
    for them in targets:
        found = _offers_with(
            players, totals, me, them, block, weights_by_team[me], weights_by_team[them],
            max_give, max_get, allow_uneven, exclude_injured,
        )  # fmt: skip
        if not found:
            continue
        ids, my_new, their_new = found
        my_cat, their_cat = _category_changes(
            totals, me, them, my_new, their_new, weights_by_team[me], weights_by_team[them]
        )
        d_me, d_them = my_cat.sum(1), their_cat.sum(1)
        floor = {WIN_WIN: 0.0, CLOSE_CALL: CLOSE_CALL_FLOOR, MAX_GAIN: -np.inf}[acceptance]
        keep = np.flatnonzero((d_me > 1e-9) & (d_them > floor - 1e-9))

        team_rows = []
        for k in keep:
            give, get, my_drop, their_drop, my_add, their_add = ids[k]
            gen_give, gen_get = sum(generic[p] for p in give), sum(generic[p] for p in get)
            lopsided = abs(gen_get - gen_give) > LOPSIDED_GAP
            if acceptance != MAX_GAIN and lopsided:
                continue
            team_rows.append(
                {
                    "partner_id": them,
                    "give_ids": give,
                    "get_ids": get,
                    "my_drop_id": my_drop,
                    "their_drop_id": their_drop,
                    "my_add_id": my_add,
                    "their_add_id": their_add,
                    "dE_me": d_me[k],
                    "dE_them": d_them[k],
                    "gen_give": gen_give,
                    "gen_get": gen_get,
                    "lopsided": lopsided,
                    **{f"dE_{c}": my_cat[k, i] for i, c in enumerate(COLUMNS)},
                    **{f"dEt_{c}": their_cat[k, i] for i, c in enumerate(COLUMNS)},
                }
            )
        rows.extend(_drop_dominated(team_rows))

    if not rows:
        return pd.DataFrame()
    deals = pd.DataFrame(rows).sort_values(["dE_me", "dE_them"], ascending=False)
    if len(targets) > 1:
        seen = {}
        picked = []
        for _, row in deals.iterrows():
            if seen.get(row["partner_id"], 0) >= per_team_cap:
                continue
            seen[row["partner_id"]] = seen.get(row["partner_id"], 0) + 1
            picked.append(row)
            if len(picked) == top:
                break
        deals = pd.DataFrame(picked)
    return deals.head(top).reset_index(drop=True)
