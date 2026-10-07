"""Trades and waiver moves for points leagues. Pure pandas/numpy, no Streamlit.

Every deal is judged by both teams' change in **expected wins a week** (model.py):
their projected weekly points change, everyone else's stay put. A point is worth the
same to every team, so win-win deals come from how rosters are built -- a 2-for-1
whose open spot a free agent fills, a team that can't start everyone it has, games
per week, injuries -- and the scoring sees all of that through the lineup.

Two speeds, as the proposal planned:
  * searches score every deal with the fast estimate (positions ignored), vectorized;
  * the best RESCORE_TOP are rescored with the full daily lineup simulation
    (lineup.py) and re-filtered and re-sorted on those numbers, which are the ones
    shown. Mock trade and Team profile use the full simulation throughout.

Rosters stay full: a team getting more players than it sends drops the players it
expects the fewest points from the rest of the way (FP/G x games left, so a player
out for weeks goes first), never one it just received; a team left short picks up the
best healthy free agents. IR players are left out, as in categories leagues.

Fairness: a deal is *lopsided* against a team when the season value it gives (points
above replacement, 0 at worst, times games left) beats what it gets by more than
LOPSIDED_SHARE of the larger side.
"""

import math
from dataclasses import dataclass, field
from itertools import combinations

import numpy as np
import pandas as pd

from points import lineup, model

WIN_WIN, CLOSE_CALL, MAX_GAIN = "win_win", "close_call", "max_gain"
CLOSE_CALL_FLOOR = -0.2  # wins a week a partner may lose in a close call
LOPSIDED_SHARE = 0.25
MAX_SEARCH_DEALS = 250_000
OFFERS_PER_TEAM_CAP = 3
RESCORE_TOP = 40
RESCORE_PER_GROUP = 10  # also rescore at least this many from each partner / status
LIKELY, COSTS_YOU, THEY_SAY_NO = "likely", "costs_you", "they_say_no"
STATUS_ORDER = {LIKELY: 0, COSTS_YOU: 1, THEY_SAY_NO: 2}


class SearchTooLarge(Exception):
    """The search would check more than MAX_SEARCH_DEALS deals; message for people."""


@dataclass
class Setup:
    """Everything the scoring needs for one league, stat window and horizon.

    players: index player_id, with player_name, team_id (NaN for free agents),
    is_free_agent, is_ir, injury_status, pro_team, slots (frozenset), fpg, par,
    games (a week, on average over the horizon, 0 while injured), games_left,
    season_value and back (first week he counts)."""

    players: pd.DataFrame
    weeks: list
    days_per_week: float
    slot_counts: dict
    day_list: list
    replacement: float
    roster_spots: int
    sigma: float = 0.0
    spread_note: str = ""
    _full: dict = field(default_factory=dict, repr=False)

    @property
    def starting(self) -> int:
        return int(sum(self.slot_counts.values()))

    @property
    def teams(self) -> list[int]:
        return sorted(int(t) for t in self.players["team_id"].dropna().unique())

    def roster(self, team: int) -> list[int]:
        """The team's players outside IR, most projected points left first (the
        order roster moves drop from: the last ones go)."""
        p = self.players
        mine = p.loc[(p["team_id"] == team) & ~p["is_ir"].astype(bool)]
        left = (mine["fpg"] * mine["games_left"]).rename("left")
        order = mine.assign(left=left).sort_values(["left", "fpg"], ascending=False, kind="stable")
        return list(order.index)

    def free_agents(self, exclude=()) -> list[int]:
        """Healthy free agents, best FP/G first."""
        p = self.players
        pool = p.loc[p["is_free_agent"].astype(bool) & model.healthy(p) & ~p.index.isin(exclude)]
        return list(pool.sort_values("fpg", ascending=False, kind="stable").index)

    def fast_mu(self, ids) -> float:
        ids = list(ids)
        if not ids:
            return 0.0
        f = self.players.loc[ids, "fpg"].to_numpy(float)
        g = self.players.loc[ids, "games"].to_numpy(float)
        return float(model.fast_weekly_points(f, g, self.days_per_week, self.starting))

    def full_weeks(self, ids) -> dict:
        """{week: projected points} from the daily lineup simulation (cached)."""
        key = frozenset(int(i) for i in ids)
        if key not in self._full:
            p = self.players.loc[list(key)]
            self._full[key] = lineup.simulate_weeks(
                list(key),
                p["fpg"].to_dict(),
                p["slots"].to_dict(),
                p["pro_team"].to_dict(),
                p["back"].to_dict(),
                self.slot_counts,
                self.day_list,
            )
        return self._full[key]

    def full_mu(self, ids) -> float:
        weeks = self.full_weeks(ids)["weeks"]
        return float(sum(weeks.get(w, 0.0) for w in self.weeks) / max(len(self.weeks), 1))

    def team_mu(self, full: bool = True) -> pd.Series:
        score = self.full_mu if full else self.fast_mu
        return pd.Series({t: score(self.roster(t)) for t in self.teams}, dtype="float64")


def build(players: pd.DataFrame, schedule: pd.DataFrame, slot_counts: dict, bench: int,
          current_week: int, last_week: int, as_of, results: pd.DataFrame) -> Setup:  # fmt: skip
    """A Setup from the league's players (with fpg), the NBA schedule and the
    finished matchups (model.played_results)."""
    players = players.copy()
    weeks = model.horizon_weeks(current_week, last_week)
    players["back"] = model.first_week_back(players, current_week, as_of)
    by_week = model.games_by_week(players, schedule, weeks, players["back"])
    players["games"] = by_week.mean(axis=1)
    players["games_left"] = by_week.sum(axis=1)
    players["slots"] = players["eligible_slots"].map(model.slots_of)
    players["fpg"] = players["fpg"].fillna(0.0)
    replacement = model.replacement_level(players)
    players["par"] = players["fpg"] - replacement
    players["season_value"] = players["par"].clip(lower=0) * players["games_left"]
    days = model.week_days(schedule, weeks)
    in_horizon = schedule.loc[schedule["matchup_period"].isin(weeks)]
    day_list = [
        (int(week), frozenset(group["pro_team"]))
        for (week, _), group in in_horizon.groupby(["matchup_period", "scoring_period"])
    ]
    setup = Setup(
        players=players,
        weeks=weeks,
        days_per_week=float(days.mean()) if len(days) else 0.0,
        slot_counts=dict(slot_counts),
        day_list=day_list,
        replacement=replacement,
        roster_spots=int(sum(slot_counts.values()) + bench),
    )
    setup.sigma, setup.spread_note = model.weekly_spread(results, setup.team_mu(full=False))
    return setup


# --- Scoring many deals at once ------------------------------------------------------------


def _packs(n: int, sizes) -> dict[int, np.ndarray]:
    """{size: index combos of that size out of range(n)} for each size."""
    return {
        k: np.array(list(combinations(range(n), k)), dtype=int).reshape(-1, k)
        for k in sizes
        if 0 < k <= n
    }


def _after(f_own, g_own, keep, f_in, g_in, extra, fa_f, fa_g):
    """One side's rosters after every (own pack, incoming pack) pair: (A*B, width)
    arrays of FP/G and games. keep: (A, m) own players kept; f_in/g_in: (B, k)
    incoming; extra: players received minus sent (drops the lowest own players kept
    when > 0, adds the free agents fa_f/fa_g when < 0). Returns (f, g, drop mask)."""
    a, m = keep.shape
    b = f_in.shape[0]
    drop = np.zeros_like(keep)
    if extra > 0:
        from_bottom = np.cumsum(keep[:, ::-1], axis=1)[:, ::-1]
        drop = keep & (from_bottom <= extra)
    stay = keep & ~drop
    own_f = np.broadcast_to(np.where(stay, f_own, 0.0)[:, None, :], (a, b, m))
    own_g = np.broadcast_to(np.where(stay, g_own, 0.0)[:, None, :], (a, b, m))
    in_f = np.broadcast_to(f_in[None, :, :], (a, b, f_in.shape[1]))
    in_g = np.broadcast_to(g_in[None, :, :], (a, b, g_in.shape[1]))
    parts_f, parts_g = [own_f, in_f], [own_g, in_g]
    if extra < 0:
        n_fa = -extra
        parts_f.append(np.broadcast_to(fa_f[:n_fa], (a, b, n_fa)))
        parts_g.append(np.broadcast_to(fa_g[:n_fa], (a, b, n_fa)))
    f = np.concatenate(parts_f, axis=2).reshape(a * b, -1)
    g = np.concatenate(parts_g, axis=2).reshape(a * b, -1)
    return f, g, drop


def _wins(mu_self: np.ndarray, mu_other: np.ndarray, others: np.ndarray, scale: float):
    """Expected wins a week for a team at mu_self, against the fixed `others` and the
    trade partner at mu_other."""
    vs_rest = model.phi((mu_self[:, None] - others[None, :]) / scale).sum(axis=1)
    return vs_rest + model.phi((mu_self - mu_other) / scale)


def score_pair(setup: Setup, me: int, them: int, my_sizes, their_sizes, *, give_pool=None,
               must_get=None, uneven: bool = True, exclude_injured: bool = False,
               base_mu: pd.Series | None = None,
               gains_only: bool = True) -> pd.DataFrame:  # fmt: skip
    """Fast scores for every deal between `me` and `them` with packages of the given
    sizes. give_pool: only these of my players may go; must_get: a player every deal
    must bring me; exclude_injured: leave out their OUT players; gains_only: keep
    only deals that raise my expected wins."""
    p = setup.players
    mine = setup.roster(me)
    if give_pool is not None:
        pool = set(give_pool)
        mine_pool = [i for i in mine if i in pool]
    else:
        mine_pool = mine
    theirs = setup.roster(them)
    their_pool = [
        i for i in theirs if not (exclude_injured and p.at[i, "injury_status"] in model.UNAVAILABLE)
    ]
    if must_get is not None and must_get not in their_pool:
        return pd.DataFrame()
    base_mu = setup.team_mu(full=False) if base_mu is None else base_mu
    others = base_mu.drop([me, them]).to_numpy(float)
    scale = math.sqrt(2) * max(setup.sigma, 1e-9)
    e_old = model.expected_wins(base_mu, setup.sigma)

    f_me, g_me = p.loc[mine, "fpg"].to_numpy(float), p.loc[mine, "games"].to_numpy(float)
    f_th, g_th = p.loc[theirs, "fpg"].to_numpy(float), p.loc[theirs, "games"].to_numpy(float)
    pos_me = {pid: i for i, pid in enumerate(mine)}
    pos_th = {pid: i for i, pid in enumerate(theirs)}
    give_idx = np.array([pos_me[i] for i in mine_pool], dtype=int)
    get_idx = np.array([pos_th[i] for i in their_pool], dtype=int)
    fas = setup.free_agents()
    fa_f = p.loc[fas, "fpg"].to_numpy(float)
    fa_g = p.loc[fas, "games"].to_numpy(float)
    v_me = p.loc[mine, "season_value"].to_numpy(float)
    v_th = p.loc[theirs, "season_value"].to_numpy(float)

    parts = []
    for kg, gives in _packs(len(give_idx), my_sizes).items():
        for kt, gets in _packs(len(get_idx), their_sizes).items():
            if not uneven and kg != kt:
                continue
            give = give_idx[gives]  # (A, kg) positions in my roster
            get = get_idx[gets]  # (B, kt) positions in their roster
            if must_get is not None:
                get = get[(get == pos_th[must_get]).any(axis=1)]
                if not len(get):
                    continue
            keep_me = np.ones((len(give), len(mine)), bool)
            np.put_along_axis(keep_me, give, False, axis=1)
            keep_th = np.ones((len(get), len(theirs)), bool)
            np.put_along_axis(keep_th, get, False, axis=1)
            fm, gm, drop_me = _after(f_me, g_me, keep_me, f_th[get], g_th[get], kt - kg,
                                     fa_f, fa_g)  # fmt: skip
            ft, gt, drop_th = _after(f_th, g_th, keep_th, f_me[give], g_me[give], kg - kt,
                                     fa_f, fa_g)  # fmt: skip
            # Partner rows come out (their pack, my pack); line them up as (mine, theirs).
            width = ft.shape[1]
            ft = ft.reshape(len(get), len(give), width).transpose(1, 0, 2).reshape(-1, width)
            gt = gt.reshape(len(get), len(give), width).transpose(1, 0, 2).reshape(-1, width)
            mu_me = model.fast_weekly_points(fm, gm, setup.days_per_week, setup.starting)
            mu_th = model.fast_weekly_points(ft, gt, setup.days_per_week, setup.starting)
            e_me = _wins(mu_me, mu_th, others, scale)
            e_th = _wins(mu_th, mu_me, others, scale)
            d_me = e_me - e_old[me]
            chosen = np.arange(len(d_me)) if not gains_only else np.flatnonzero(d_me > 1e-9)
            if not len(chosen):
                continue
            i, j = np.divmod(chosen, len(get))
            v_give = v_me[give].sum(axis=1)[i]
            v_get = v_th[get].sum(axis=1)[j]
            give_ids = [tuple(int(x) for x in row) for row in np.asarray(mine)[give]]
            get_ids = [tuple(int(x) for x in row) for row in np.asarray(theirs)[get]]
            my_drops = [tuple(int(mine[x]) for x in np.flatnonzero(r)) for r in drop_me]
            their_drops = [tuple(int(theirs[x]) for x in np.flatnonzero(r)) for r in drop_th]
            parts.append(
                pd.DataFrame(
                    {
                        "partner_id": int(them),
                        "give_ids": [give_ids[x] for x in i],
                        "get_ids": [get_ids[x] for x in j],
                        "my_drop_ids": [my_drops[x] for x in i],
                        "their_drop_ids": [their_drops[x] for x in j],
                        "my_add_ids": [tuple(int(x) for x in fas[: max(kg - kt, 0)])] * len(i),
                        "their_add_ids": [tuple(int(x) for x in fas[: max(kt - kg, 0)])] * len(i),
                        "dmu_me": mu_me[chosen] - base_mu[me],
                        "dmu_them": mu_th[chosen] - base_mu[them],
                        "dE_me": d_me[chosen],
                        "dE_them": e_th[chosen] - e_old[them],
                        "value_give": v_give,
                        "value_get": v_get,
                        "lopsided": (v_give - v_get)
                        > LOPSIDED_SHARE * np.maximum(np.maximum(v_give, v_get), 1e-9),
                        "full": False,
                    }
                )
            )
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def lopsided(value_out_for_them: float, value_in_for_them: float) -> bool:
    """Against the partner: they give more season value than they get, by more than
    LOPSIDED_SHARE of the larger side. (From my side: what I get vs what I give.)"""
    gap = value_out_for_them - value_in_for_them
    return gap > LOPSIDED_SHARE * max(value_out_for_them, value_in_for_them, 1e-9)


def after_rosters(setup: Setup, me: int, deal) -> tuple[list, list]:
    """(my roster, their roster) after a deal row, roster moves included."""
    mine = [p for p in setup.roster(me) if p not in deal["give_ids"] + deal["my_drop_ids"]]
    mine += [*deal["get_ids"], *deal["my_add_ids"]]
    them = int(deal["partner_id"])
    theirs = [p for p in setup.roster(them) if p not in deal["get_ids"] + deal["their_drop_ids"]]
    theirs += [*deal["give_ids"], *deal["their_add_ids"]]
    return mine, theirs


def full_scores(setup: Setup, rosters: dict) -> tuple[pd.Series, pd.Series, pd.Series]:
    """(mu before, mu after, E change) for every team with the full simulation,
    `rosters` replacing some teams' rosters."""
    before = setup.team_mu(full=True)
    after = before.copy()
    for team, ids in rosters.items():
        after[team] = setup.full_mu(ids)
    change = model.expected_wins(after, setup.sigma) - model.expected_wins(before, setup.sigma)
    return before, after, change


def rescore(setup: Setup, me: int, deals: pd.DataFrame, top: int = RESCORE_TOP,
            by: str | None = "partner_id",
            per_group: int = RESCORE_PER_GROUP) -> pd.DataFrame:  # fmt: skip
    """The `top` deals by fast gain, plus the best `per_group` of each `by` group (so
    no partner, or status, is crowded out), rescored with the full daily simulation."""
    if deals.empty:
        return deals
    ranked = deals.sort_values(["dE_me", "dE_them"], ascending=False)
    chosen = ranked.head(top).index
    if by is not None and by in ranked:
        chosen = chosen.union(ranked.groupby(by, sort=False).head(per_group).index)
    best = ranked.loc[ranked.index.isin(chosen)].copy()
    for k, deal in best.iterrows():
        mine, theirs = after_rosters(setup, me, deal)
        them = int(deal["partner_id"])
        before, after, change = full_scores(setup, {me: mine, them: theirs})
        best.loc[k, ["dmu_me", "dmu_them", "dE_me", "dE_them"]] = [
            after[me] - before[me], after[them] - before[them], change[me], change[them],
        ]  # fmt: skip
        best.loc[k, "full"] = True
    return best


def _accept(deals: pd.DataFrame, acceptance: str) -> pd.DataFrame:
    floor = {WIN_WIN: 0.0, CLOSE_CALL: CLOSE_CALL_FLOOR, MAX_GAIN: -np.inf}[acceptance]
    ok = (deals["dE_me"] > 1e-9) & (deals["dE_them"] > floor - 1e-9)
    if acceptance != MAX_GAIN:
        ok &= ~deals["lopsided"]
    return deals.loc[ok]


def _cap_per_team(deals: pd.DataFrame, cap: int, top: int) -> pd.DataFrame:
    picked = deals.groupby("partner_id", sort=False).head(cap)
    return picked.head(top).reset_index(drop=True)


def _drop_dominated(deals: pd.DataFrame) -> pd.DataFrame:
    """Drop a deal when the same deal without one of the players I get gains me as
    much (a throw-in that adds nothing)."""
    if deals.empty:
        return deals
    gain = {(r.partner_id, r.give_ids, frozenset(r.get_ids)): r.dE_me for r in deals.itertuples()}
    keep = []
    for r in deals.itertuples():
        got = frozenset(r.get_ids)
        smaller = [gain.get((r.partner_id, r.give_ids, got - {p}), -np.inf) for p in got]
        keep.append(not (len(got) > 1 and max(smaller) >= r.dE_me - 1e-9))
    return deals.loc[keep]


# --- The searches -------------------------------------------------------------------------


def find_trades(setup: Setup, me: int, top: int = 15,
                rescore_top: int = RESCORE_TOP) -> pd.DataFrame:  # fmt: skip
    """Trade finder: every 1-for-1, 2-for-1, 1-for-2 and 2-for-2 deal with every team
    that both teams gain from (win-win, not lopsided), best for me first."""
    base = setup.team_mu(full=False)
    found = [
        score_pair(setup, me, them, (1, 2), (1, 2), base_mu=base)
        for them in setup.teams
        if them != me
    ]
    deals = pd.concat([d for d in found if not d.empty] or [pd.DataFrame()], ignore_index=True)
    if deals.empty:
        return deals
    deals = _accept(deals, WIN_WIN)
    deals = _accept(rescore(setup, me, deals, rescore_top), WIN_WIN)
    deals = _drop_dominated(deals).sort_values(["dE_me", "dE_them"], ascending=False)
    return deals.head(top).reset_index(drop=True)


def status(deal) -> str:
    fair = deal["dE_them"] >= -1e-9 and not deal["lopsided"]
    if deal["dE_me"] > 1e-9:
        return LIKELY if fair else THEY_SAY_NO
    return COSTS_YOU if fair else THEY_SAY_NO


def deals_for_target(setup: Setup, me: int, target: int, max_size: int = 2,
                     top: int = 15) -> pd.DataFrame:  # fmt: skip
    """Every deal (up to max_size-for-max_size) that brings `target` to me, labelled
    likely to work, costs you (his realistic price) or they'd likely say no."""
    them = setup.players.at[target, "team_id"]
    if pd.isna(them) or int(them) == me:
        return pd.DataFrame()
    sizes = tuple(range(1, max_size + 1))
    deals = score_pair(setup, me, int(them), sizes, sizes, must_get=target, gains_only=False)
    if deals.empty:
        return deals
    deals["status"] = deals.apply(status, axis=1)
    deals = rescore(setup, me, deals, top=0, by="status")
    deals = deals.loc[deals["full"]].copy()
    deals["status"] = deals.apply(status, axis=1)
    deals["order"] = deals["status"].map(STATUS_ORDER)
    deals = deals.sort_values(["order", "dE_me", "dE_them"], ascending=[True, False, False])
    return deals.drop(columns="order").head(top).reset_index(drop=True)


def offer_search_size(block: int, rosters: list[int], max_give: int, max_get: int,
                      uneven: bool) -> int:  # fmt: skip
    gives = {k: math.comb(block, k) for k in range(1, min(max_give, block) + 1)}
    total = 0
    for n in rosters:
        gets = {k: math.comb(n, k) for k in range(1, min(max_get, n) + 1)}
        if uneven:
            total += sum(gives.values()) * sum(gets.values())
        else:
            total += sum(gives.get(k, 0) * gets.get(k, 0) for k in gets)
    return total


def build_offers(setup: Setup, me: int, block, targets, max_give: int = 2, max_get: int = 2,
                 acceptance: str = WIN_WIN, exclude_injured: bool = True, uneven: bool = True,
                 top: int = 15, per_team_cap: int = OFFERS_PER_TEAM_CAP,
                 max_search: int = MAX_SEARCH_DEALS,
                 rescore_top: int = RESCORE_TOP) -> pd.DataFrame:  # fmt: skip
    """Offer Builder: deals built only from `block` against each team in `targets`
    that raise my expected wins, filtered by `acceptance` (win_win, close_call,
    max_gain). Raises SearchTooLarge before any work past max_search deals."""
    mine = set(setup.roster(me))
    block = [int(b) for b in block if int(b) in mine]
    targets = [int(t) for t in targets if int(t) != me]
    if not block or not targets:
        return pd.DataFrame()
    p = setup.players

    def eligible(team):
        roster = setup.roster(team)
        if exclude_injured:
            roster = [i for i in roster if p.at[i, "injury_status"] not in model.UNAVAILABLE]
        return len(roster)

    size = offer_search_size(len(block), [eligible(t) for t in targets], max_give, max_get,
                             uneven)  # fmt: skip
    if size > max_search:
        raise SearchTooLarge(
            f"That search would check {size:,} deals, more than the {max_search:,} limit. "
            "Pick fewer players for your trade block, or lower the max sizes."
        )
    base = setup.team_mu(full=False)
    found = [
        score_pair(
            setup,
            me,
            them,
            range(1, max_give + 1),
            range(1, max_get + 1),
            give_pool=block,
            uneven=uneven,
            exclude_injured=exclude_injured,
            base_mu=base,
        )  # fmt: skip
        for them in targets
    ]
    deals = pd.concat([d for d in found if not d.empty] or [pd.DataFrame()], ignore_index=True)
    if deals.empty:
        return deals
    deals = _accept(deals, acceptance)
    deals = _accept(rescore(setup, me, deals, rescore_top), acceptance)
    deals = _drop_dominated(deals).sort_values(["dE_me", "dE_them"], ascending=False)
    return _cap_per_team(deals, per_team_cap if len(targets) > 1 else top, top)


def waiver_moves(setup: Setup, me: int, top: int = 15, candidates: int = 40) -> pd.DataFrame:
    """Add a free agent (and drop one of my players, unless I have an open spot):
    every pair of the `candidates` best free agents and my players, best first."""
    roster = setup.roster(me)
    open_spot = len(roster) < setup.roster_spots
    base = setup.team_mu(full=False)
    others = base.drop(me).to_numpy(float)
    scale = math.sqrt(2) * max(setup.sigma, 1e-9)
    e_old = model.expected_wins(base, setup.sigma)[me]
    moves = [
        (fa, drop)
        for fa in setup.free_agents()[:candidates]
        for drop in ([None] if open_spot else []) + roster
    ]
    if not moves:
        return pd.DataFrame()
    width = len(roster) + 1
    f = np.zeros((len(moves), width))
    g = np.zeros((len(moves), width))
    p = setup.players
    for n, (fa, drop) in enumerate(moves):
        ids = [i for i in roster if i != drop] + [fa]
        f[n, : len(ids)] = p.loc[ids, "fpg"].to_numpy(float)
        g[n, : len(ids)] = p.loc[ids, "games"].to_numpy(float)
    mu = model.fast_weekly_points(f, g, setup.days_per_week, setup.starting)
    e = model.phi((mu[:, None] - others[None, :]) / scale).sum(axis=1)
    found = pd.DataFrame(
        {
            "add_id": [fa for fa, _ in moves],
            "drop_id": [drop for _, drop in moves],
            "dmu": mu - base[me],
            "dE": e - e_old,
            "full": False,
        }
    )
    found = found.loc[found["dE"] > 1e-9].sort_values("dE", ascending=False).head(RESCORE_TOP)
    for k, move in found.iterrows():
        ids = [i for i in roster if i != move["drop_id"]] + [int(move["add_id"])]
        before, after, change = full_scores(setup, {me: ids})
        found.loc[k, ["dmu", "dE", "full"]] = [after[me] - before[me], change[me], True]
    found = found.loc[found["dE"] > 1e-9].sort_values("dE", ascending=False)
    found["drop_id"] = found["drop_id"].astype("object")
    return found.head(top).reset_index(drop=True)


def mock(setup: Setup, me: int, them: int | None, give=(), get=(), my_add=(), my_drop=(),
         their_add=(), their_drop=()) -> dict:  # fmt: skip
    """A hand-built move, scored with the full simulation for both teams: rosters
    after, projected weekly points and expected wins before and after."""
    mine = [p for p in setup.roster(me) if p not in (*give, *my_drop)] + [*get, *my_add]
    rosters = {me: mine}
    if them is not None:
        theirs = [p for p in setup.roster(them) if p not in (*get, *their_drop)]
        rosters[them] = theirs + [*give, *their_add]
    before, after, change = full_scores(setup, rosters)
    e_before = model.expected_wins(before, setup.sigma)
    return {
        "rosters": rosters,
        "mu_before": before,
        "mu_after": after,
        "e_before": e_before,
        "e_after": e_before + change,
        "dE": change,
    }
