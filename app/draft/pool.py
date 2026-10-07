"""The draft pool: every draftable player as aligned arrays the engine can index.

Format-agnostic parts (who, where, the consensus board, positions and slots) live in
`Pool`; `points_format` turns a pool into PointsFormat values. A categories format will
add its own builder beside it.

The consensus board ("key", lower = taken earlier) blends ESPN's average draft
position with ESPN's draft rank for the league's format (STANDARD for points, ROTO for
categories): ADP pools every format and the whole preseason, so a room drafting by
categories lets players whose categories rank lags their ADP fall. Replaying two real
categories drafts, 3/4 ADP + 1/4 the format's rank predicted who'd still be there 10
picks later best (Brier score 0.124, against 0.137 for ADP alone). ESPN's ADP also
flattens out near the end of a typical draft (about pick 130, where every deep player
sits near 140), so from there on the ADP part follows the rank too.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

POSITIONS = ["PG", "SG", "SF", "PF", "C"]
ADP_PLATEAU = 0.93  # ADP above this share of the pool's largest ADP no longer ranks players
PLATEAU_SHARE = 0.1  # ...if at least this share of the pool (and 10 players) bunch near the top
RANK_WEIGHT = 0.25  # the format's ESPN rank's share of the board key
RISKS = {
    "ignore": "Ignore: ESPN's projected games",
    "neutral": "Neutral: games capped by his last 3 seasons",
    "avoid": "Avoid: capped, and 15% fewer for players who miss a lot",
}
FULL_SEASON = 82
MISSES_A_LOT = 60  # average games a season below which "avoid" trims his games


def board_keys(adp: pd.Series, rank: pd.Series, weight: float = RANK_WEIGHT) -> pd.Series:
    """The consensus order: (1 - weight) x ADP (while it's informative, then the rank
    order after it) + weight x the format's ESPN rank."""
    adp = adp.where(adp > 0)
    rank = rank.astype(float).fillna(rank.max() + 1 if rank.notna().any() else 999)
    top = float(adp.max()) if adp.notna().any() else 0.0
    bunched = int((adp >= 0.97 * top).sum())
    flat = bunched >= max(10, PLATEAU_SHARE * len(adp))
    plateau = ADP_PLATEAU * top if flat else top
    informative = adp.notna() & ((adp < plateau) if flat else True)
    order = rank.where(~informative).rank(method="first")
    by_adp = adp.where(informative, plateau + order)
    return (1 - weight) * by_adp + weight * rank


def projected_games(proj: pd.Series, history: pd.Series, injured: pd.Series,
                    risk: str) -> pd.Series:  # fmt: skip
    """Games for the season: ESPN's projection, capped by the player's average over his
    last 3 seasons unless risk is "ignore"; "avoid" trims another 15% from players who
    average under 60 games or are OUT now."""
    games = proj.fillna(history).fillna(0.0).clip(upper=FULL_SEASON)
    if risk == "ignore":
        return games
    games = np.minimum(games, history.fillna(games))
    if risk == "avoid":
        fragile = (history < MISSES_A_LOT) | injured
        games = games.where(~fragile, games * 0.85)
    return games


@dataclass
class Pool:
    """Players in board order, index 0..P-1. frame columns: player_id, player_name,
    pro_team, position, slots (frozenset of starting slots), injury_status, adp, rank,
    key, plus format values."""

    frame: pd.DataFrame
    slot_types: list  # starting slot types that need specific players (UT left out)
    slot_counts: np.ndarray  # how many of each

    @property
    def ids(self) -> np.ndarray:
        return self.frame["player_id"].to_numpy()

    @property
    def key(self) -> np.ndarray:
        return self.frame["key"].to_numpy(float)

    @property
    def position(self) -> np.ndarray:
        return self.frame["position"].map(POSITIONS.index).fillna(-1).to_numpy(int)

    @property
    def eligible(self) -> np.ndarray:
        """(P, K): can each player start in each slot type."""
        return np.array(
            [[slot in slots for slot in self.slot_types] for slots in self.frame["slots"]],
            dtype=bool,
        ).reshape(len(self.frame), len(self.slot_types))

    def index_of(self) -> dict:
        return {int(pid): i for i, pid in enumerate(self.ids)}


def build(raw: pd.DataFrame, lineup_slots: dict, rank_column: str = "rank") -> Pool:
    """A Pool from draft_pool rows (one per player), the league's starting slots and
    the ESPN rank its format drafts by (the format's rank_column)."""
    frame = raw.copy()
    frame["slots"] = frame["eligible_slots"].map(
        lambda s: frozenset(x for x in str(s or "").split(",") if x)
    )
    frame["key"] = board_keys(frame["adp"], frame[rank_column])
    frame = frame.sort_values(["key", "rank"], kind="stable").reset_index(drop=True)
    types = [s for s in lineup_slots if s != "UT"]
    return Pool(frame, types, np.array([lineup_slots[s] for s in types], dtype=int))
