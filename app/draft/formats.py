"""How a league format values rosters, for the draft engine.

The engine (simulate.py, recommend.py) is the same for every format. It asks a format
for three things, on rosters given as index arrays into the draft pool (-1 = an empty
spot or a player outside the pool):

  strength(rosters)    (..., teams, size) -> each team's strength, (..., teams) for a
                       number (points: projected weekly points) or (..., teams, k)
                       for a profile (categories: each category's projected total)
  expected_wins(s)     strengths -> each team's expected wins against all the others,
                       (..., teams). This is what the draft maximizes for you, so a
                       pick is judged against the rosters the other teams build.
  pick_value           (pool,) a value per player, for ordering your own later picks in
                       the simulations and for the Value column
  rank_column          which ESPN draft rank rooms of this format draft by: "rank"
                       (STANDARD, points) or "rank_roto" (ROTO, categories); it's
                       blended into the opponents' board (pool.py)

Points is PointsFormat below. Categories will be a second class with the same three
methods: strength = the category totals of each roster's projected z lines (the Trade
Analyzer's team totals, analysis.pool), expected_wins = expected category wins against
every other team (analysis.objective), pick_value = general value (the z total),
rank_column = "rank_roto". The board, pick entry, opponent model and simulations don't
change.
"""

import math
from abc import ABC, abstractmethod

import numpy as np

from points import model


class DraftFormat(ABC):
    wins_label = "Expected wins"
    strength_label = "Strength"
    rank_column = "rank"

    @abstractmethod
    def strength(self, rosters: np.ndarray) -> np.ndarray:
        """Each team's strength from its roster's pool indexes (-1 = nobody)."""

    @abstractmethod
    def expected_wins(self, strength: np.ndarray) -> np.ndarray:
        """Each team's expected wins against every other team: (..., teams)."""

    @property
    @abstractmethod
    def pick_value(self) -> np.ndarray:
        """A value per pool player; higher is better."""

    def max_wins(self, teams: int) -> float:
        return float(teams - 1)

    def strength_number(self, strength: np.ndarray) -> np.ndarray:
        """One number per team for tables and charts (a profile's headline)."""
        return strength


class PointsFormat(DraftFormat):
    """Head-to-head points: strength is projected weekly points (the points engine's
    fast estimate: each day the best `starting` players with a game start), and
    expected wins come from each team's weekly points as a bell curve with a spread
    of `spread` of an average team's week."""

    wins_label = "Expected wins a week"
    strength_label = "Projected points a week"
    rank_column = "rank"  # ESPN's STANDARD (points) draft rank

    def __init__(self, fpg, games_week, days_week: float, starting: int, value,
                 spread: float = model.DEFAULT_SPREAD):  # fmt: skip
        # A trailing zero player, so index -1 (nobody) adds nothing.
        self._fpg = np.append(np.asarray(fpg, float), 0.0)
        self._games = np.append(np.asarray(games_week, float), 0.0)
        self._value = np.asarray(value, float)
        self.days_week = float(days_week)
        self.starting = int(starting)
        self.spread = float(spread)

    @property
    def pick_value(self) -> np.ndarray:
        return self._value

    def strength(self, rosters: np.ndarray) -> np.ndarray:
        rosters = np.asarray(rosters)
        return model.fast_weekly_points(
            self._fpg[rosters], self._games[rosters], self.days_week, self.starting
        )

    def expected_wins(self, strength: np.ndarray) -> np.ndarray:
        s = np.asarray(strength, float)
        sigma = np.maximum(self.spread * s.mean(axis=-1, keepdims=True), 1e-9)
        diff = (s[..., :, None] - s[..., None, :]) / (math.sqrt(2) * sigma[..., None])
        p = model.phi(diff)
        teams = s.shape[-1]
        p = p * (1 - np.eye(teams))  # a team doesn't play itself
        return p.sum(axis=-1)
