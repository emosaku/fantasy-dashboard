"""Fitting the opponent model to real drafts.

What the tool needs from the model is the chance a player is still there some picks
later. So the model is fitted by replaying real drafts: from the real state before
many picks, it predicts who's still there 10 picks on, and the settings that predict
what really happened best (lowest Brier score: the mean squared gap between predicted
chance and outcome) win. The settings are the noise: sd = noise_base + noise_share x
key. The position cap is read
straight off the real rosters: the most players any team took at one position, as a
share of the rounds. stage_profile also compares how far picks stray from the board,
stage by stage, as a second check.

Pure numpy/pandas over the engine's own simulate(), so it fits exactly the model the
tool runs.
"""

import itertools

import numpy as np
import pandas as pd

from draft.formats import DraftFormat
from draft.pool import POSITIONS, Pool
from draft.simulate import OpponentModel, simulate
from draft.state import Draft

STAGE_PICKS = 20  # deviations are compared in stages of 20 picks


def real_deviations(picks: list, pool: Pool) -> pd.DataFrame:
    """One row per real pick of a pool player: overall pick, his key, and pick - key."""
    index_of = pool.index_of()
    key = pool.key
    rows = [
        {"overall": k, "key": key[index_of[p]], "player": p}
        for k, (_, p) in enumerate(picks, start=1)
        if p in index_of
    ]
    out = pd.DataFrame(rows)
    out["deviation"] = out["overall"] - out["key"]
    return out


def simulated_deviations(order, pool: Pool, fmt: DraftFormat, model: OpponentModel,
                         runs: int = 60, seed: int = 0) -> pd.DataFrame:  # fmt: skip
    """The same table from `runs` simulated drafts where every team is a manager."""
    watch = tuple(range(1, order.total + 1))
    r = simulate(Draft(order), pool, fmt, model, None, runs, seed, watch=watch)
    key = pool.key
    frames = [
        pd.DataFrame({"overall": k, "key": key[r.choices[k]], "run": np.arange(runs)})
        for k in watch
    ]
    out = pd.concat(frames, ignore_index=True)
    out["deviation"] = out["overall"] - out["key"]
    return out


def stage_profile(deviations: pd.DataFrame, total: int) -> np.ndarray:
    """Mean |pick - key| in each stage of STAGE_PICKS picks."""
    stages = np.arange(0, total, STAGE_PICKS)
    stage = (deviations["overall"] - 1) // STAGE_PICKS * STAGE_PICKS
    means = deviations["deviation"].abs().groupby(stage).mean()
    return means.reindex(stages).to_numpy(float)


def position_cap_share(picks: list, pool: Pool, rounds: int) -> float:
    """The most players any team took at one position, as a share of the rounds."""
    position = dict(zip(pool.ids.tolist(), pool.frame["position"], strict=True))
    counts: dict = {}
    for team, player in picks:
        pos = position.get(player)
        if pos in POSITIONS:
            counts[(team, pos)] = counts.get((team, pos), 0) + 1
    return max(counts.values(), default=0) / rounds


def availability_check(order, picks: list, pool: Pool, fmt: DraftFormat, model: OpponentModel,
                       every: int = 5, ahead: int = 10, runs: int = 200,
                       seed: int = 0) -> pd.DataFrame:  # fmt: skip
    """Replay a real draft: from the real state before pick k (every `every` picks),
    the model's chance that each of the 40 players next on the board is still there at
    pick k + ahead, beside whether he really was. A calibrated model's 20% players last
    about 20% of the time."""
    taken_at = {p: k for k, (_, p) in enumerate(picks, start=1)}
    rows = []
    for k in range(1, order.total - ahead + 1, every):
        state = Draft(order, list(picks[: k - 1]))
        target = k + ahead
        r = simulate(state, pool, fmt, model, None, runs, seed, watch=(target,))
        there = r.available_at[target].mean(axis=0)
        gone = state.taken()
        board = [i for i in np.argsort(pool.key) if int(pool.ids[i]) not in gone][:40]
        for i in board:
            pid = int(pool.ids[i])
            rows.append(
                {
                    "pick": k,
                    "player": pid,
                    "predicted": float(there[i]),
                    "lasted": taken_at.get(pid, order.total + 1) >= target,
                }
            )
    return pd.DataFrame(rows)


def reliability(check: pd.DataFrame, bins=(0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0001)) -> pd.DataFrame:
    """Predicted vs actual share that lasted, by bin of predicted chance."""
    bucket = pd.cut(check["predicted"], bins, right=False)
    return check.groupby(bucket, observed=True).agg(
        players=("lasted", "size"), predicted=("predicted", "mean"), lasted=("lasted", "mean")
    )


BASES = (0.0, 1.0, 3.0, 5.0)
SHARES = (0.05, 0.1, 0.15, 0.2, 0.3)


def brier(check: pd.DataFrame) -> float:
    return float(((check["predicted"] - check["lasted"]) ** 2).mean())


def fit(drafts: list, runs: int = 60, every: int = 10,
        seed: int = 0) -> tuple[OpponentModel, pd.DataFrame]:  # fmt: skip
    """drafts: [(order, picks [(team, player)], pool, fmt)]. Returns the model whose
    replayed availability predictions score best, and the grid searched, best first."""
    cap_share = max(position_cap_share(p, pool, o.rounds) for o, p, pool, _ in drafts)
    rows = []
    for base, share in itertools.product(BASES, SHARES):
        model = OpponentModel(base, share, cap_share)
        checks = [availability_check(o, p, pool, fmt, model, every, 10, runs, seed)
                  for o, p, pool, fmt in drafts]  # fmt: skip
        rows.append({"noise_base": base, "noise_share": share,
                     "brier": brier(pd.concat(checks))})  # fmt: skip
    grid = pd.DataFrame(rows).sort_values("brier", ignore_index=True)
    best = grid.iloc[0]
    model = OpponentModel(float(best["noise_base"]), float(best["noise_share"]), cap_share)
    return model, grid


class BoardOnly(DraftFormat):
    """A stand-in format for fitting the opponent model, which only needs the board:
    no values, every team even. Lets any league's real draft be used, whatever its
    format."""

    def __init__(self, size: int):
        self._value = np.zeros(size)

    @property
    def pick_value(self) -> np.ndarray:
        return self._value

    def strength(self, rosters: np.ndarray) -> np.ndarray:
        return np.zeros(np.asarray(rosters).shape[:-1])

    def expected_wins(self, strength: np.ndarray) -> np.ndarray:
        return np.zeros(np.asarray(strength).shape)
