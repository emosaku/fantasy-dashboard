"""Three-team trades: three packages move around a circle.

A circle is three teams (me, a, b): I send a package to a, a sends one to b, and b
sends one to me. Each team gives one package and gets one back, so nobody has to want
what I have except a. Every team is scored the way the two-team searches score a
side -- its own change in category wins (E), its own punts zeroed -- except that
three teams' totals change at once, so each team is compared with the teams the deal
doesn't touch and with the other two teams' new totals.

Rosters stay full by the two-team rule (trades.fill_roster): a team that receives
more players than it sends drops its lowest-valued remaining ones, never one it just
received; a team left short picks up the best available free agents, by its own
weights.

The searches score every candidate deal exactly. Each team's new totals depend on
only two packages (the one it sends and the one it gets), so they're built once per
pair of packages, and the three-way comparison runs vectorized over the whole grid
of (my package, a's package, b's package). That keeps the full search fast enough
that it needs no shortcut that could miss a deal.

ESPN only trades between two teams, so a circle is done as two linked trades through
a middle team (middle_plans).
"""

from dataclasses import dataclass
from itertools import combinations

import numpy as np
import pandas as pd

from analysis.objective import category_wins, head_to_head
from analysis.pool import contribution
from analysis.trades import (
    CLOSE_CALL,
    CLOSE_CALL_FLOOR,
    LOPSIDED_GAP,
    MAX_GAIN,
    WIN_WIN,
    SearchTooLarge,
    _side_delta,
    as_ids,
    fill_roster,
)
from analysis.weights import generic_values, player_values, punts
from categories import COLUMNS

MAX_CIRCLE_DEALS = 6_000_000  # deals scored per search: about 1 s on a 14-team league
TOP_DEALS = 10
DEALS_PER_PAIR = 2
SHORTLIST = 6
_CHUNK = 150_000  # grid cells scored at once, to bound memory
_EPS = 1e-9

FLOORS = {WIN_WIN: 0.0, CLOSE_CALL: CLOSE_CALL_FLOOR, MAX_GAIN: -np.inf}


# --- One deal: who sends what, and the score ---------------------------------------


def circle_moves(circle, packages) -> dict:
    """team -> (players it sends, players it gets). circle = (me, a, b): I send
    packages[0] to a, a sends packages[1] to b, b sends packages[2] to me."""
    me, a, b = circle
    p_me, p_a, p_b = (tuple(p) for p in packages)
    return {me: (p_me, p_b), a: (p_a, p_me), b: (p_b, p_a)}


@dataclass
class CircleResult:
    after: pd.DataFrame  # team totals after the deal
    sides: dict  # team -> SideResult
    fills: dict  # team -> (drops, adds) that keep its roster full


def simulate_circle(
    players: pd.DataFrame,
    totals: pd.DataFrame,
    circle,
    packages,
    weights_by_team: dict,
    my_drop=None,
    my_add=None,
    fill_mine: bool = True,
    empty=None,
) -> CircleResult:
    """All three teams' totals and results after a circle. Partners always keep
    their rosters full by the two-team rule. My side does too when fill_mine (the
    searches); otherwise my_drop / my_add are my own moves (the Mock trade), and
    `empty` (pool.empty_slot_z) charges each spot I'm left short."""
    me = circle[0]
    after = totals.copy()
    fills = {}
    for team, (sent, received) in circle_moves(circle, packages).items():
        if team == me and not fill_mine:
            drops, adds = tuple(as_ids(my_drop)), tuple(as_ids(my_add))
        else:
            drops, adds = fill_roster(players, team, sent, received, weights_by_team[team])
        fills[team] = (drops, adds)
        ins, outs = [*received, *adds], [*sent, *drops]
        change = contribution(players, ins) - contribution(players, outs)
        short = len(outs) - len(ins)
        if empty is not None and short > 0:
            change = change + short * empty.reindex(totals.columns).fillna(0).to_numpy()
        after.loc[team] = after.loc[team].to_numpy() + change
    sides = {t: _side_delta(totals, after, t, punts(weights_by_team[t])) for t in circle}
    return CircleResult(after, sides, fills)


# --- Getting it done on ESPN: two linked trades through a middle team ---------------


def middle_plans(players: pd.DataFrame, totals: pd.DataFrame, circle, packages,
                 weights_by_team: dict) -> list[dict]:  # fmt: skip
    """The three ways to run a circle as two ESPN trades, least risky first. Each
    plan's middle team makes both trades: trade 1 with the team it would send to,
    trade 2 with the other. `between` is the middle team's change in category wins
    if trade 2 never happens (players only, before any roster moves): the risk it
    carries. Every plan ends with the same rosters."""
    teams, packs = list(circle), [tuple(p) for p in packages]
    generic = generic_values(players)
    plans = []
    for i in range(3):
        middle, first, second = teams[i], teams[(i + 1) % 3], teams[(i + 2) % 3]
        t1_send, t1_get = packs[i], packs[(i + 1) % 3]
        t2_send, t2_get = t1_get, packs[(i + 2) % 3]
        after = totals.copy()
        after.loc[middle] += contribution(players, t1_get) - contribution(players, t1_send)
        after.loc[first] += contribution(players, t1_send) - contribution(players, t1_get)
        between = _side_delta(totals, after, middle, punts(weights_by_team[middle]))
        between_first = _side_delta(totals, after, first, punts(weights_by_team[first]))

        def lopsided(sent, got) -> bool:
            return bool(abs(generic[list(sent)].sum() - generic[list(got)].sum()) > LOPSIDED_GAP)

        plans.append(
            {
                "middle": middle,
                "trade1": {"with": first, "middle_sends": t1_send, "middle_gets": t1_get,
                           "lopsided": lopsided(t1_send, t1_get)},
                "trade2": {"with": second, "middle_sends": t2_send, "middle_gets": t2_get,
                           "lopsided": lopsided(t2_send, t2_get)},
                "between": between.delta_e,
                "between_first": between_first.delta_e,
                # >0: the middle holds extra players between the trades; <0: it's short.
                "between_roster": len(t1_get) - len(t1_send),
            }
        )  # fmt: skip
    return sorted(plans, key=lambda p: -p["between"])


# --- The search ----------------------------------------------------------------------


def _packages(ids, max_size: int, must=None) -> list[tuple]:
    """Every package of 1..max_size of `ids`; with `must`, only those holding him
    (him alone, or him and one more)."""
    ids = [int(p) for p in ids]
    if must is None:
        return [c for size in range(1, max_size + 1) for c in combinations(ids, size)]
    others = [p for p in ids if p != must]
    return [(int(must),)] + ([(int(must), p) for p in others] if max_size >= 2 else [])


@dataclass
class _Side:
    """One team's candidate packages, precomputed for the grid."""

    team: int
    packs: list
    z: np.ndarray  # (n, 9): each package's z sum
    gen: np.ndarray  # (n,): each package's general value
    size: np.ndarray  # (n,)
    drop_cum: np.ndarray  # (n, max_k + 1, 9): z of the k lowest-valued players left
    add_cum: np.ndarray  # (max_k + 1, 9): z of the k best free agents for this team
    index: dict  # package -> row


def _side(players, team, packs, weights, generic, max_k, fa_order) -> _Side:
    roster = players.loc[(players["team_id"] == team) & ~players["is_ir"]]
    order = player_values(roster, weights).sort_values(kind="stable").index.to_numpy()
    z_by_id = roster[COLUMNS]
    n = len(packs)
    z = np.zeros((n, len(COLUMNS)))
    drop_cum = np.zeros((n, max_k + 1, len(COLUMNS)))
    for row, pack in enumerate(packs):
        z[row] = players.loc[list(pack), COLUMNS].to_numpy().sum(0)
        left = [p for p in order if p not in pack][:max_k]
        if left:
            sums = np.cumsum(z_by_id.loc[left].to_numpy(), axis=0)
            drop_cum[row, 1 : len(left) + 1] = sums
            drop_cum[row, len(left) + 1 :] = sums[-1]
    adds = fa_order(weights)[:max_k]
    add_cum = np.zeros((max_k + 1, len(COLUMNS)))
    if len(adds):
        sums = np.cumsum(players.loc[adds, COLUMNS].to_numpy(), axis=0)
        add_cum[1 : len(adds) + 1] = sums
        add_cum[len(adds) + 1 :] = sums[-1]
    return _Side(
        team=int(team),
        packs=packs,
        z=z,
        gen=np.array([sum(generic[p] for p in pack) for pack in packs]),
        size=np.array([len(p) for p in packs]),
        drop_cum=drop_cum,
        add_cum=add_cum,
        index={p: k for k, p in enumerate(packs)},
    )


def _new_rows(total: np.ndarray, sender: _Side, received: _Side) -> np.ndarray:
    """(sends, receives, 9): the team's new totals for every pair of packages,
    rosters kept full."""
    max_k = sender.add_cum.shape[0] - 1
    diff = received.size[None, :] - sender.size[:, None]
    drops = sender.drop_cum[np.arange(len(sender.packs))[:, None], np.clip(diff, 0, max_k)]
    adds = sender.add_cum[np.clip(-diff, 0, max_k)]
    return total - sender.z[:, None, :] + received.z[None, :, :] - drops + adds


def _score_grid(totals: pd.DataFrame, sides: tuple, masks: dict) -> tuple:
    """dE for (me, a, b) over every (i, j, k): I send packs i, a sends j, b sends k.
    Arrays of shape (ni, nj, nk)."""
    s_me, s_a, s_b = sides
    me, a, b = s_me.team, s_a.team, s_b.team
    t = {team: totals.loc[team].to_numpy() for team in (me, a, b)}
    new_me = _new_rows(t[me], s_me, s_b)  # (ni, nk, 9)
    new_a = _new_rows(t[a], s_a, s_me)  # (nj, ni, 9)
    new_b = _new_rows(t[b], s_b, s_a)  # (nk, nj, 9)
    others = totals.drop([me, a, b]).to_numpy()

    def fixed(rows, team):
        return (category_wins(rows, others) * masks[team]).sum(-1)

    def base(team):
        return float((category_wins(t[team], totals.drop(team).to_numpy()) * masks[team]).sum())

    f_me, f_a, f_b = fixed(new_me, me), fixed(new_a, a), fixed(new_b, b)
    b_me, b_a, b_b = base(me), base(a), base(b)
    ni, nj, nk = len(s_me.packs), len(s_a.packs), len(s_b.packs)
    d_me, d_a, d_b = (np.empty((ni, nj, nk)) for _ in range(3))
    B = new_b.transpose(1, 0, 2)[None]  # (1, nj, nk, 9)
    step = max(1, _CHUNK // max(1, nj * nk))
    for lo in range(0, ni, step):
        sl = slice(lo, min(ni, lo + step))
        ME = new_me[sl][:, None]  # (c, 1, nk, 9)
        A = new_a[:, sl].transpose(1, 0, 2)[:, :, None]  # (c, nj, 1, 9)
        me_a, me_b, a_b = head_to_head(ME, A), head_to_head(ME, B), head_to_head(A, B)
        d_me[sl] = f_me[sl][:, None, :] + ((me_a + me_b) * masks[me]).sum(-1) - b_me
        d_a[sl] = f_a[:, sl].T[:, :, None] + ((1 - me_a + a_b) * masks[a]).sum(-1) - b_a
        d_b[sl] = f_b.T[None] + ((2 - me_b - a_b) * masks[b]).sum(-1) - b_b
    return d_me, d_a, d_b


def _best_in_circle(sides, totals, masks, acceptance, min_gain, keep) -> list[dict]:
    """The circle's `keep` best deals that pass, near-duplicates dropped."""
    d_me, d_a, d_b = _score_grid(totals, sides, masks)
    s_me, s_a, s_b = sides
    floor = FLOORS[acceptance]
    ok = (d_me > min_gain + _EPS) & (d_a > floor - _EPS) & (d_b > floor - _EPS)
    if acceptance != MAX_GAIN:  # a partner whose side looks lopsided won't take it
        lop_a = np.abs(s_me.gen[:, None] - s_a.gen[None, :]) > LOPSIDED_GAP  # (i, j)
        lop_b = np.abs(s_a.gen[:, None] - s_b.gen[None, :]) > LOPSIDED_GAP  # (j, k)
        ok &= ~lop_a[:, :, None] & ~lop_b[None, :, :]
    cells = np.flatnonzero(ok)
    if not len(cells):
        return []
    moved = s_me.size[:, None, None] + s_a.size[None, :, None] + s_b.size[None, None, :]
    flat = {"me": d_me.ravel(), "a": d_a.ravel(), "b": d_b.ravel(), "n": moved.ravel()}
    weaker = np.minimum(flat["a"][cells], flat["b"][cells])
    cells = cells[np.lexsort((flat["n"][cells], -weaker, -flat["me"][cells]))]
    shape = d_me.shape

    def dominated(i, j, k) -> bool:
        """A version with one player fewer that passes and gains me as much."""
        here = d_me[i, j, k]
        for axis, side, pos in ((0, s_me, i), (1, s_a, j), (2, s_b, k)):
            pack = side.packs[pos]
            for p in pack if len(pack) > 1 else ():
                smaller = side.index.get(tuple(x for x in pack if x != p))
                if smaller is None:
                    continue
                cell = [i, j, k]
                cell[axis] = smaller
                if ok[tuple(cell)] and d_me[tuple(cell)] >= here - _EPS:
                    return True
        return False

    found = []
    for cell in cells:
        i, j, k = np.unravel_index(cell, shape)
        if dominated(i, j, k):
            continue
        found.append(
            {
                "circle": (s_me.team, s_a.team, s_b.team),
                "packages": (s_me.packs[i], s_a.packs[j], s_b.packs[k]),
                "dE_me": float(d_me[i, j, k]),
                "weaker": float(min(d_a[i, j, k], d_b[i, j, k])),
                "moved": int(moved[i, j, k]),
            }
        )
        if len(found) == keep:
            break
    return found


def _rows(players, totals, picked, weights_by_team) -> pd.DataFrame:
    """The picked deals as rows, scored exactly by simulate_circle."""
    generic = generic_values(players)
    rows = []
    for deal in picked:
        circle, packages = deal["circle"], deal["packages"]
        me, a, b = circle
        result = simulate_circle(players, totals, circle, packages, weights_by_team)
        moves = circle_moves(circle, packages)

        def gen(team):
            sent, got = moves[team]
            return float(generic[list(sent)].sum()), float(generic[list(got)].sum())

        rows.append(
            {
                "circle": circle,
                "partner_a": a,
                "partner_b": b,
                "give_ids": packages[0],
                "a_sends": packages[1],
                "get_ids": packages[2],
                "fills": result.fills,
                "dE_me": result.sides[me].delta_e,
                "dE_a": result.sides[a].delta_e,
                "dE_b": result.sides[b].delta_e,
                "cat_me": result.sides[me].cat_delta.to_dict(),
                "cat_a": result.sides[a].cat_delta.to_dict(),
                "cat_b": result.sides[b].cat_delta.to_dict(),
                "gen": {t: gen(t) for t in circle},
                "lopsided_a": abs(gen(a)[0] - gen(a)[1]) > LOPSIDED_GAP,
                "lopsided_b": abs(gen(b)[0] - gen(b)[1]) > LOPSIDED_GAP,
                "moved": deal["moved"],
            }
        )
    return pd.DataFrame(rows)


def _pick(found: list[dict], top: int, per_pair_cap: int) -> list[dict]:
    """Best first (my gain, then the weaker partner's, then fewer players moved), at
    most per_pair_cap from any pair of partners."""
    found = sorted(found, key=lambda d: (-d["dE_me"], -d["weaker"], d["moved"]))
    picked, per_pair = [], {}
    for deal in found:
        pair = frozenset(deal["circle"][1:])
        if per_pair.get(pair, 0) >= per_pair_cap:
            continue
        per_pair[pair] = per_pair.get(pair, 0) + 1
        picked.append(deal)
        if len(picked) == top:
            break
    return picked


def _context(players, weights_by_team, max_size):
    generic = generic_values(players).to_dict()
    fa = players.loc[players["is_free_agent"] & (players["injury_status"] != "OUT")]
    fa_cache = {}

    def fa_order(weights):
        key = id(weights)
        if key not in fa_cache:
            values = player_values(fa, weights).sort_values(ascending=False, kind="stable")
            fa_cache[key] = values.index.to_numpy()
        return fa_cache[key]

    masks = {t: (~np.isin(COLUMNS, punts(w))).astype(float) for t, w in weights_by_team.items()}
    return generic, fa_order, masks, max(0, max_size - 1)


def _guard(size: int, max_search: int, advice: str) -> None:
    if size > max_search:
        raise SearchTooLarge(
            f"That search would check {size:,} three-team deals, more than the "
            f"{max_search:,} limit. {advice}"
        )


def _active(players, team, exclude_out=False) -> list[int]:
    rows = players.loc[(players["team_id"] == team) & ~players["is_ir"]]
    if exclude_out:
        rows = rows.loc[rows["injury_status"] != "OUT"]
    return [int(p) for p in rows.index]


def three_team_for_target(
    players: pd.DataFrame,
    totals: pd.DataFrame,
    me: int,
    target,
    weights_by_team: dict,
    third: int | None = None,
    max_size: int = 2,
    acceptance: str = WIN_WIN,
    exclude_injured: bool = True,
    min_gain: float = 0.0,
    top: int = TOP_DEALS,
    per_pair_cap: int = DEALS_PER_PAIR,
    max_search: int = MAX_CIRCLE_DEALS,
) -> pd.DataFrame:
    """Unlock a player: circles that bring `target` to me. His team sends him (alone
    or with one teammate) to me; I send to a third team, which sends to his team. One
    circle per third team (`third`, or every other team). I must gain more than
    `min_gain` (the page passes the best two-team deal's gain, since two trades are
    harder to land than one); both partners must pass `acceptance`."""
    target = int(target)
    them = int(players.at[target, "team_id"])
    thirds = [int(third)] if third is not None else [
        int(t) for t in totals.index if t not in (me, them)
    ]  # fmt: skip
    mates = [p for p in _active(players, them, exclude_out=exclude_injured) if p != target]
    p_them = _packages([target, *mates], max_size, must=target)
    p_me = _packages(_active(players, me), max_size)
    p_third = {t: _packages(_active(players, t), max_size) for t in thirds}
    size = sum(len(p_me) * len(p_third[t]) * len(p_them) for t in thirds)
    _guard(size, max_search, "Name the third team or use 1 player per package.")

    generic, fa_order, masks, max_k = _context(players, weights_by_team, max_size)
    s_me = _side(players, me, p_me, weights_by_team[me], generic, max_k, fa_order)
    s_them = _side(players, them, p_them, weights_by_team[them], generic, max_k, fa_order)
    found = []
    for t in thirds:
        if not p_third[t] or not p_me:
            continue
        s_t = _side(players, t, p_third[t], weights_by_team[t], generic, max_k, fa_order)
        found += _best_in_circle((s_me, s_t, s_them), totals, masks, acceptance, min_gain,
                                 per_pair_cap)  # fmt: skip
    picked = _pick(found, top, per_pair_cap)
    return _rows(players, totals, picked, weights_by_team) if picked else pd.DataFrame()


def partner_shortlist(players: pd.DataFrame, team: int, weights, n: int = SHORTLIST) -> list[int]:
    """A partner's most movable players: worth the least to his own team compared with
    their general value (the Trade chips rule), skipping anyone OUT or on IR."""
    rows = players.loc[_active(players, team, exclude_out=True)]
    surplus = generic_values(rows) - player_values(rows, weights)
    return [int(p) for p in surplus.sort_values(ascending=False, kind="stable").index[:n]]


def three_team_offers(
    players: pd.DataFrame,
    totals: pd.DataFrame,
    me: int,
    block,
    weights_by_team: dict,
    partners=(),
    max_size: int = 2,
    acceptance: str = WIN_WIN,
    shortlist: int = SHORTLIST,
    top: int = TOP_DEALS,
    per_pair_cap: int = DEALS_PER_PAIR,
    max_search: int = MAX_CIRCLE_DEALS,
) -> pd.DataFrame:
    """From my trade block: circles where I send only players from `block`, with every
    pair of partners (both directions round the circle). `partners` names none, one
    (paired with every other team) or two. Each partner offers its `shortlist` most
    movable players."""
    mine = set(_active(players, me))
    block = [int(p) for p in block if int(p) in mine]
    partners = [int(t) for t in partners if t != me]
    others = [int(t) for t in totals.index if t != me]
    if len(partners) >= 2:
        pairs = [tuple(partners[:2])]
    elif len(partners) == 1:
        pairs = [(partners[0], t) for t in others if t != partners[0]]
    else:
        pairs = list(combinations(others, 2))
    if not block or not pairs:
        return pd.DataFrame()

    p_me = _packages(block, max_size)
    lists = {
        t: _packages(partner_shortlist(players, t, weights_by_team[t], shortlist), max_size)
        for t in {t for pair in pairs for t in pair}
    }
    size = sum(2 * len(p_me) * len(lists[x]) * len(lists[y]) for x, y in pairs)
    _guard(size, max_search, "Name a partner, put fewer players on your block, use 1 player "
                             "per package, or a shorter partner shortlist.")  # fmt: skip

    generic, fa_order, masks, max_k = _context(players, weights_by_team, max_size)
    s_me = _side(players, me, p_me, weights_by_team[me], generic, max_k, fa_order)
    sides = {
        t: _side(players, t, packs, weights_by_team[t], generic, max_k, fa_order)
        for t, packs in lists.items()
        if packs
    }
    found = []
    for x, y in pairs:
        if x not in sides or y not in sides:
            continue
        for a, b in ((x, y), (y, x)):
            found += _best_in_circle((s_me, sides[a], sides[b]), totals, masks, acceptance,
                                     0.0, per_pair_cap)  # fmt: skip
    picked = _pick(found, top, per_pair_cap)
    return _rows(players, totals, picked, weights_by_team) if picked else pd.DataFrame()
