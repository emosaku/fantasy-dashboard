"""Your best picks, and where every team stands, for any league format.

At your next pick (now, if you're on the clock) every candidate X is scored as

    score(X) = average over runs of your expected wins once every roster is full,
               if you plan to take X at that pick

using simulate.py with the same random numbers for every candidate. If X is gone
before your pick in a run, you take your best available instead, so the score already
includes the chance he won't be there. The five highest are your picks.

Each pick comes with what drives it: his value, the chance he lasts to your following
pick, the empty starting slots he fills, the team most likely to take him if you don't,
and who you'd likely take next. The same runs give the League view: every team's
projected finished strength and expected wins, and its chance of finishing first.
"""

from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd

from draft.formats import DraftFormat
from draft.pool import Pool
from draft.simulate import OpponentModel, Runs, simulate
from draft.state import Draft

SHORTLIST = 14  # candidates simulated: the best by value among those likely there
LIKELY_THERE = 0.05


@dataclass
class Advice:
    pick: int | None  # your next pick number (None: you have no picks left)
    on_clock: bool
    picks: pd.DataFrame  # the top candidates, best first
    league: pd.DataFrame  # every team: strength now, projected strength and wins, rank
    base: Runs


def _rank_of(wins: np.ndarray, t: int) -> np.ndarray:
    """Your rank (1 = most expected wins) in each run."""
    return 1 + (wins > wins[:, [t]]).sum(axis=1)


def league_table(draft: Draft, pool: Pool, fmt: DraftFormat, runs: Runs) -> pd.DataFrame:
    """Every team: strength of the players it has now, and its projected finished
    strength, expected wins and rank, averaged over the runs."""
    index_of = pool.index_of()
    current = draft.rosters()
    size = max([len(v) for v in current.values()] + [1])
    now = np.full((1, len(runs.teams), size), -1, dtype=int)
    for i, team in enumerate(runs.teams):
        for j, player in enumerate(current.get(team, [])):
            now[0, i, j] = index_of.get(player, -1)
    strength_now = fmt.strength_number(fmt.strength(now))[0]
    final = fmt.strength_number(runs.strength).mean(axis=0)
    wins = runs.wins
    ranks = np.stack([_rank_of(wins, t) for t in range(len(runs.teams))], axis=1)
    return pd.DataFrame(
        {
            "team_id": runs.teams,
            "players": [len(current.get(t, [])) for t in runs.teams],
            "strength_now": strength_now,
            "strength": final,
            "wins": wins.mean(axis=0),
            "rank": ranks.mean(axis=0),
            "first": (ranks == 1).mean(axis=0),
        }
    ).sort_values("wins", ascending=False, ignore_index=True)


def recommend(draft: Draft, pool: Pool, fmt: DraftFormat, model: OpponentModel, me: int,
              runs: int = 200, top: int = 5, shortlist: int = SHORTLIST,
              seed: int = 0) -> Advice:  # fmt: skip
    upcoming = draft.next_pick_of(me)
    following = draft.next_pick_of(me, after=upcoming + 1) if upcoming else None
    watch = tuple(k for k in (upcoming, following) if k)
    base = simulate(draft, pool, fmt, model, me, runs, seed, watch=watch)
    league = league_table(draft, pool, fmt, base)
    if upcoming is None:
        return Advice(None, False, pd.DataFrame(), league, base)

    t = base.team(me)
    there = base.available_at[upcoming].mean(axis=0)
    lasts = base.available_at[following].mean(axis=0) if following else np.zeros(len(pool.frame))
    value = np.asarray(fmt.pick_value, float)
    open_now = np.ones(len(pool.frame), dtype=bool)
    index_of = pool.index_of()
    for player in draft.taken():
        if player in index_of:
            open_now[index_of[player]] = False
    likely = np.flatnonzero(open_now & (there >= LIKELY_THERE))
    candidates = likely[np.argsort(-value[likely], kind="stable")][:shortlist]
    owner_of = _owners(base, candidates)

    rows, results = [], {}
    for c in candidates:
        r = simulate(draft, pool, fmt, model, me, runs, seed, force=int(c), force_pick=upcoming,
                     watch=(following,) if following else ())  # fmt: skip
        results[int(c)] = r
        mine = r.wins[:, t]
        nxt = Counter(r.choices[following].tolist()).most_common(3) if following else []
        rows.append(
            {
                "index": int(c),
                "player_id": int(pool.ids[c]),
                "wins": float(mine.mean()),
                "strength": float(fmt.strength_number(r.strength)[:, t].mean()),
                "rank": float(_rank_of(r.wins, t).mean()),
                "there": float(there[c]),
                "lasts": float(lasts[c]),
                "got": float((r.rosters[:, t, :] == c).any(axis=1).mean()),
                "value": float(value[c]),
                "taken_by": owner_of.get(int(c)),
                "next": [(int(i), n / runs) for i, n in nxt],
            }
        )
    # Ties (rare in points) go to the stronger finished roster.
    picks = pd.DataFrame(rows).sort_values(["wins", "strength"], ascending=False,
                                           ignore_index=True)  # fmt: skip
    if not picks.empty:
        best = results[int(picks.at[0, "index"])].wins[:, t]
        second = picks.at[1, "wins"] if len(picks) > 1 else picks.at[0, "wins"]
        picks["edge"] = picks["wins"] - picks.at[0, "wins"]
        picks.loc[0, "edge"] = picks.at[0, "wins"] - second
        picks["se"] = [
            float(np.std(results[int(i)].wins[:, t] - best) / np.sqrt(runs)) for i in picks["index"]
        ]
    return Advice(upcoming, draft.on_clock == me, picks.head(top), league, base)


def _owners(runs: Runs, candidates) -> dict:
    """For each candidate: (team id, share of runs) of the team that ends up with him
    most often when you don't plan on him -- who you'd be taking him from."""
    out = {}
    for c in candidates:
        has = (runs.rosters == c).any(axis=2)  # (runs, teams)
        counts = has.sum(axis=0)
        if counts.sum():
            t = int(np.argmax(counts))
            out[int(c)] = (runs.teams[t], float(counts[t] / len(runs.rosters)))
    return out


def fills(pool: Pool, roster: list, player: int) -> list:
    """The starting slot types still empty on `roster` (pool indexes) that the player
    at pool index `player` can fill."""
    eligible = pool.eligible
    have = eligible[[i for i in roster if i >= 0]].sum(axis=0) if roster else 0
    empty = np.asarray(pool.slot_counts) - have > 0
    return [
        s for s, e, ok in zip(pool.slot_types, empty, eligible[player], strict=True) if e and ok
    ]
