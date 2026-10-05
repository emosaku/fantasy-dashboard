"""Category weights and tiers: which categories are worth fighting for, per team.

A category's weight for team t is how many opponents a realistic change of delta
(default 1.0 z, about one solid starter) would flip:
  U = opponents whose total is in (T, T + delta]  -- teams you'd pass with a gain
  D = opponents whose total is in [T - delta, T)  -- teams that would pass you
  raw weight = (U + 0.5 D) / (N - 1)
Gains count fully and losses half, because the analyzer looks for upgrades. The 9
weights are then scaled to sum to 9 (average 1.0).

Tiers: Lock = top 3 with D = 0; Punt = bottom 3 with U = 0 (weight 0); Swing = the
rest. "Top/bottom 3" is ranks 1-3 / 12-14 in this 14-team league. A user override
(Lock / Swing / Punt) replaces the raw weight with 0.5 / 1.5 / 0 before scaling.
"""

import pandas as pd

from categories import COLUMNS

OVERRIDE_WEIGHTS = {"Lock": 0.5, "Swing": 1.5, "Punt": 0.0}
TIERS = ["Lock", "Swing", "Punt"]


def compute_weights(
    totals: pd.DataFrame, team_id: int, delta: float = 1.0, overrides: dict | None = None
) -> pd.DataFrame:
    """One row per category: total, rank, gap_above, gap_below, U, D, auto_tier,
    tier (after overrides), weight. overrides maps category -> "Auto"/"Lock"/...."""
    n = len(totals)
    me = totals.loc[team_id, COLUMNS]
    diff = totals.drop(team_id)[COLUMNS] - me  # each opponent's total minus mine

    up = ((diff > 0) & (diff <= delta)).sum()
    down = ((diff < 0) & (diff >= -delta)).sum()
    rank = totals[COLUMNS].rank(ascending=False, method="min").loc[team_id].astype(int)

    auto_tier = pd.Series("Swing", index=COLUMNS)
    auto_tier[(rank <= 3) & (down == 0)] = "Lock"
    auto_tier[(rank >= n - 2) & (up == 0)] = "Punt"

    raw = (up + 0.5 * down) / (n - 1)
    raw[auto_tier == "Punt"] = 0.0
    tier = auto_tier.copy()
    for category, choice in (overrides or {}).items():
        if choice in OVERRIDE_WEIGHTS:
            tier[category] = choice
            raw[category] = OVERRIDE_WEIGHTS[choice]

    if raw.sum() > 0:
        weight = raw * len(COLUMNS) / raw.sum()
    else:  # nothing is within reach anywhere: fall back to equal weights
        weight = pd.Series(1.0, index=COLUMNS)
        weight[tier == "Punt"] = 0.0

    return pd.DataFrame(
        {
            "total": me,
            "rank": rank,
            "gap_above": diff.where(diff > 0).min(),
            "gap_below": (-diff).where(diff < 0).min(),
            "up": up,
            "down": down,
            "auto_tier": auto_tier,
            "tier": tier,
            "weight": weight,
        }
    )


def punts(weights: pd.DataFrame) -> list[str]:
    return list(weights.index[weights["tier"] == "Punt"])


def player_values(players: pd.DataFrame, weights: pd.DataFrame) -> pd.Series:
    """v_t(p): each player's z-scores weighted by team t's category weights."""
    return players[COLUMNS] @ weights.loc[COLUMNS, "weight"]


def generic_values(players: pd.DataFrame) -> pd.Series:
    """Unweighted total z -- the same for every team; used for fairness checks."""
    return players[COLUMNS].sum(axis=1)
