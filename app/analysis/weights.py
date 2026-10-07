"""Category weights and tiers: which categories are worth fighting for, per team.

A category's weight for team t is how many opponents a realistic change of delta
(default 1.0 z, about one solid starter) would flip:
  U = opponents whose total is in (T, T + delta]  -- teams you'd pass with a gain
  D = opponents whose total is in [T - delta, T)  -- teams that would pass you
  raw weight = (U + 0.5 D) / (N - 1)
Gains count fully and losses half, because the analyzer looks for upgrades. The
league's K weights are then scaled to sum to K (average 1.0).

Tiers: Lock = top 3 with D = 0; Punt = bottom 3 with U = 0 (weight 0); Swing = the
rest. "Bottom 3" is the last three ranks, whatever the league size. A user override
(Lock / Swing / Punt) replaces the raw weight with 0.5 / 1.5 / 0 before scaling.
"""

import pandas as pd

from analysis.pool import cat_cols

OVERRIDE_WEIGHTS = {"Lock": 0.5, "Swing": 1.5, "Punt": 0.0}
TIERS = ["Lock", "Swing", "Punt"]


def compute_weights(
    totals: pd.DataFrame, team_id: int, delta: float = 1.0, overrides: dict | None = None
) -> pd.DataFrame:
    """One row per category: total, rank, gap_above, gap_below, U, D, auto_tier,
    tier (after overrides), weight. overrides maps category -> "Auto"/"Lock"/...."""
    n = len(totals)
    cols = list(totals.columns)
    me = totals.loc[team_id, cols]
    diff = totals.drop(team_id)[cols] - me  # each opponent's total minus mine

    up = ((diff > 0) & (diff <= delta)).sum()
    down = ((diff < 0) & (diff >= -delta)).sum()
    rank = totals[cols].rank(ascending=False, method="min").loc[team_id].astype(int)

    auto_tier = pd.Series("Swing", index=cols)
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
        weight = raw * len(cols) / raw.sum()
    else:  # nothing is within reach anywhere: fall back to equal weights
        weight = pd.Series(1.0, index=cols)
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
    cols = list(weights.index)
    return players[cols] @ weights.loc[cols, "weight"]


def generic_values(players: pd.DataFrame) -> pd.Series:
    """Unweighted total z -- the same for every team; used for fairness checks."""
    return players[cat_cols(players)].sum(axis=1)


def player_fit(players: pd.DataFrame, player_ids, weights: pd.DataFrame) -> pd.DataFrame:
    """Compare page's "Fit for your team" row: each player's value to the team
    `weights` was computed for (v = player_values, the same number the Trade
    Analyzer shows), next to his generic (unweighted) total z, and how that value
    splits across the team's tiers in words, e.g. "70% of his value is in your
    Swing categories" -- two players with similar overall ranks can look very
    different here. Only categories where the player adds positive weighted value
    count toward the split; one with none gets an empty breakdown. A player not in
    `players` (no stat line this window) gets None/empty throughout."""
    present = [p for p in player_ids if p in players.index]
    by_id = {}
    if present:
        sub = players.loc[present]
        v = player_values(sub, weights)
        generic = generic_values(sub)
        for pid in present:
            cols = list(weights.index)
            contribution = sub.loc[pid, cols] * weights.loc[cols, "weight"]
            positive = contribution[contribution > 0]
            by_tier = positive.groupby(weights.loc[positive.index, "tier"]).sum()
            total = by_tier.sum()
            if total > 0:
                breakdown = "; ".join(
                    f"{100 * amount / total:.0f}% of his value is in your {tier} categories"
                    for tier, amount in by_tier.sort_values(ascending=False).items()
                )
            else:
                breakdown = "no positive value in any category for this team"
            by_id[pid] = {"value": v[pid], "generic": generic[pid], "tier_breakdown": breakdown}
    out = pd.DataFrame(
        [
            by_id.get(pid, {"value": None, "generic": None, "tier_breakdown": ""})
            for pid in player_ids
        ],
        index=pd.Index(list(player_ids), name="player_id"),
    )
    return out
