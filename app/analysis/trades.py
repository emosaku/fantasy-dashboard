"""Trade simulation and the trade finder.

simulate_trade applies one deal to the team totals and reports both sides' change
in E per category. find_trades searches every 1-for-1 and 2-for-1 deal (both
directions) with every other team, vectorized over team-total arrays -- a deal only
changes two teams' rows -- and keeps the win-win ones. The Mock trade tab runs
simulate_trade on the same inputs, so a loaded deal shows the same numbers.

Roster size stays even on both sides. The side receiving two players for one drops
its lowest-valued remaining player (by its own weights), never one it just received.
The side giving two for one is left a player short, so it picks up the best
available free agent by its own weights -- what a real manager would do with the
open slot. Without that, every 2-for-1 looked like a free upgrade for whoever got
two players. IR players are left out of the search: they add nothing while on IR.
"""

from dataclasses import dataclass
from itertools import combinations

import numpy as np
import pandas as pd

from analysis.objective import category_wins, head_to_head
from analysis.pool import contribution
from analysis.weights import generic_values, player_values, punts

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

    delta = pd.Series(wins(after) - wins(before), index=after.columns)
    delta[list(punted)] = 0.0
    return SideResult(team_id, delta, float(delta.sum()))


def present(player_id) -> bool:
    """A drop slot can hold None, or NaN once it has been through a DataFrame."""
    return player_id is not None and not pd.isna(player_id)


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
) -> pd.DataFrame:
    """Team totals after a deal. them=None means the free-agent pool (a waiver move:
    `give` are drops, `get` are pickups); only my row changes then. *_drop / *_add
    are the roster-size moves that go with the deal."""

    def moved(ids_out, ids_in, drop, add):
        delta = contribution(players, ids_in) - contribution(players, ids_out)
        if present(drop):
            delta = delta - contribution(players, [drop])
        if present(add):
            delta = delta + contribution(players, [add])
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
) -> tuple[pd.DataFrame, SideResult, SideResult | None]:
    """(totals after, my result, their result or None for a free-agent move)."""
    after = apply_trade(
        players, totals, me, them, give, get, my_drop, their_drop, my_add, their_add
    )
    mine = _side_delta(totals, after, me, punts_me)
    theirs = None if them is None else _side_delta(totals, after, them, punts_them)
    return after, mine, theirs


def _lowest(values: np.ndarray, excluded: np.ndarray) -> np.ndarray:
    """For each row of `excluded` (k x m booleans), the index of the lowest value
    not excluded."""
    masked = np.where(excluded, np.inf, values[None, :])
    return masked.argmin(axis=1)


def _deals_with(players, totals, me, them, weights_me, weights_them):
    """Every 1-for-1 and 2-for-1 deal with one partner, as arrays."""
    mine = players.loc[(players["team_id"] == me) & ~players["is_ir"]]
    theirs = players.loc[(players["team_id"] == them) & ~players["is_ir"]]
    if mine.empty or theirs.empty:
        return []
    cols = list(totals.columns)
    za, zb = mine[cols].to_numpy(), theirs[cols].to_numpy()
    va = player_values(mine, weights_me).to_numpy()
    vb = player_values(theirs, weights_them).to_numpy()
    ida, idb = mine.index.to_numpy(), theirs.index.to_numpy()
    na, nb = len(ida), len(idb)
    my_pick, their_pick = best_pickup(players, weights_me), best_pickup(players, weights_them)
    z_my_pick = players.loc[my_pick, cols].to_numpy(float) if my_pick is not None else 0
    z_their_pick = players.loc[their_pick, cols].to_numpy(float) if their_pick is not None else 0

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

    my_new = np.empty((len(shapes), len(cols)))
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
    cols = list(totals.columns)
    punt_me = np.isin(cols, punts(weights_by_team[me]))
    base_me = category_wins(totals.loc[me].to_numpy(), totals.drop(me).to_numpy())
    generic = generic_values(players)
    rows = []
    for them in totals.index:
        if them == me:
            continue
        found = _deals_with(players, totals, me, them, weights_by_team[me], weights_by_team[them])
        if not found:
            continue
        ids, my_new, their_new = found
        punt_them = np.isin(cols, punts(weights_by_team[them]))
        fixed = totals.drop([me, them]).to_numpy()
        base_them = category_wins(totals.loc[them].to_numpy(), totals.drop(them).to_numpy())

        my_cat = category_wins(my_new, fixed) + head_to_head(my_new, their_new) - base_me
        their_cat = category_wins(their_new, fixed) + head_to_head(their_new, my_new) - base_them
        my_cat[:, punt_me] = 0.0
        their_cat[:, punt_them] = 0.0
        d_me, d_them = my_cat.sum(1), their_cat.sum(1)

        keep = np.flatnonzero((d_me > 1e-9) & (d_them > -1e-9))
        for k in keep:
            give, get, my_drop, their_drop, my_add, their_add = ids[k]
            gen_give, gen_get = generic[list(give)].sum(), generic[list(get)].sum()
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
                    **{f"dE_{c}": my_cat[k, i] for i, c in enumerate(cols)},
                }
            )
    if not rows:
        return pd.DataFrame()
    deals = pd.DataFrame(rows).sort_values(["dE_me", "dE_them"], ascending=False)
    return deals.head(top).reset_index(drop=True)


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
