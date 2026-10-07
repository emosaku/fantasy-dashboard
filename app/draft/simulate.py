"""Playing out the rest of a draft, many times at once, for any league format.

Each run starts from the picks made so far and plays every remaining pick:

  * Other managers draft like people. Each has a board of his own -- the consensus
    order (pool.key) plus his own noise, drawn once per run -- and takes the best
    player left on it,
    steered by his roster: at most `cap` players at one position, and once his
    remaining picks only just cover the starting slots he hasn't filled, only a
    player who fills one.
  * You draft by the format's pick_value under the same roster rules -- except at
    `force_pick`, where you take `force` if he's still there.

When every roster is full, the format turns each team's roster into a strength and
the strengths into expected wins. So a pick is judged by where your finished team
stands against the finished teams around it: what he adds to you, what's likely left
for you later, and whom he keeps from the team that would have taken him.

Runs share their random numbers: with the same seed, two calls differ only by your
choice, so comparing two candidates compares like with like. Vectorized across runs;
the loop is over picks. Knows nothing about points or categories (formats.py).
"""

import math
from dataclasses import dataclass, field

import numpy as np

from draft.formats import DraftFormat
from draft.pool import POSITIONS, Pool
from draft.state import Draft

TAKEN = np.inf
BREAKS_RULE = 1e6  # a pick that breaks a roster rule: only if nothing else is left


@dataclass(frozen=True)
class OpponentModel:
    """How far managers stray from the consensus board: a manager's board puts a
    player at key + N(0, sd), sd = noise_base + noise_share x key (later picks stray
    further). cap_share of the rounds, rounded down, is the most players one team
    takes at one position.

    Fitted by calibrate.py on two real 2026-27 drafts (10 teams x 13 rounds and 14 x
    12, both categories): replaying them, these settings predicted best who'd still be
    there 10 picks later (Brier score 0.124), and six players at one position was the
    most any real team took. A manager-level "fade" and a room-level shift per player
    were tried and didn't predict better."""

    noise_base: float = 3.0
    noise_share: float = 0.2
    cap_share: float = 0.5

    def cap(self, rounds: int) -> int:
        return max(2, math.floor(rounds * self.cap_share + 1e-9))


@dataclass
class Runs:
    teams: list  # team ids, the order of the team axis
    rosters: np.ndarray  # (runs, teams, size) pool indexes, -1 = nobody
    strength: np.ndarray  # (runs, teams[, k])
    wins: np.ndarray  # (runs, teams)
    available_at: dict = field(default_factory=dict)  # pick -> (runs, P) before it
    choices: dict = field(default_factory=dict)  # pick -> (runs,) pool index taken

    def team(self, team_id: int) -> int:
        return self.teams.index(team_id)


def simulate(draft: Draft, pool: Pool, fmt: DraftFormat, model: OpponentModel, me: int | None,
             runs: int = 200, seed: int = 0, force: int | None = None,
             force_pick: int | None = None, watch=()) -> Runs:  # fmt: skip
    """Play out the draft `runs` times. me: your team (None: every team is a manager
    like the others). force / force_pick: the pool index you take at that pick if he's
    still there. watch: pick numbers whose available players (before the pick) and
    choices are kept."""
    order = draft.order
    teams = [int(t) for t in order.teams]
    t_index = {t: i for i, t in enumerate(teams)}
    p_count = len(pool.frame)
    index_of = pool.index_of()
    future = list(range(draft.next_pick, order.total + 1))
    owners = [order.owner(k) for k in future]
    current = draft.rosters()
    sizes = [len(current.get(t, [])) + owners.count(t) for t in teams]
    size = max(sizes) if sizes else 0

    rng = np.random.default_rng(seed)
    key = pool.key
    noise = model.noise_base + model.noise_share * key
    boards = key + noise * rng.standard_normal((runs, len(teams), p_count))
    value = np.nan_to_num(np.asarray(fmt.pick_value, float), nan=-np.inf)
    my_score = np.broadcast_to(-value, (runs, p_count))

    position = pool.position
    eligible = pool.eligible.astype(float)  # (P, K)
    need = pool.slot_counts.astype(float)  # (K,)
    cap = model.cap(order.rounds)

    rosters = np.full((runs, len(teams), max(size, 1)), -1, dtype=int)
    fill = np.zeros(len(teams), dtype=int)
    available = np.ones((runs, p_count), dtype=bool)
    at_position = np.zeros((runs, len(teams), len(POSITIONS)))
    covered = np.zeros((runs, len(teams), len(need)))
    every = np.arange(runs)

    def place(t: int, choice: np.ndarray) -> None:
        rosters[every, t, fill[t]] = choice
        fill[t] += 1
        known = choice >= 0
        if not known.any():
            return
        rows, picked = every[known], choice[known]
        available[rows, picked] = False
        pos = position[picked]
        ok = pos >= 0
        at_position[rows[ok], t, pos[ok]] += 1
        covered[rows, t, :] += eligible[picked]

    for team, player in draft.picks:
        idx = index_of.get(int(player), -1)
        place(t_index[int(team)], np.full(runs, idx, dtype=int))

    picks_left = {t: owners.count(t) for t in teams}
    out = Runs(teams, rosters, None, None)
    for k, owner in zip(future, owners, strict=True):
        t = t_index[owner]
        score = (my_score if owner == me else boards[:, t, :]).copy()
        score[~available] = TAKEN
        if (position >= 0).any():
            full = at_position[:, t, :] >= cap  # (runs, positions)
            over = np.zeros((runs, p_count), dtype=bool)
            has_pos = position >= 0
            over[:, has_pos] = full[:, position[has_pos]]
            score += BREAKS_RULE * over
        if len(need):
            unmet = np.clip(need - covered[:, t, :], 0, None)  # (runs, K)
            must = picks_left[owner] <= unmet.sum(axis=1)
            fills = ((unmet > 0).astype(float) @ eligible.T) > 0  # (runs, P)
            score += BREAKS_RULE * (must[:, None] & ~fills)
        if k in watch:
            out.available_at[k] = available.copy()
        choice = np.argmin(score, axis=1)
        if owner == me and force is not None and k == force_pick:
            choice = np.where(available[:, force], force, choice)
        if k in watch:
            out.choices[k] = choice.copy()
        place(t, choice)
        picks_left[owner] -= 1

    out.strength = fmt.strength(rosters)
    out.wins = fmt.expected_wins(out.strength)
    return out
