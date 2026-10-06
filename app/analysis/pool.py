"""Turns v_player_z rows into the two frames the analysis works on."""

import numpy as np
import pandas as pd

INFO_COLUMNS = ["player_name", "team_id", "is_free_agent", "is_ir", "injury_status", "position"]


def cat_cols(df: pd.DataFrame) -> list[str]:
    """The category columns of a players frame: everything that isn't player info."""
    return [c for c in df.columns if c not in INFO_COLUMNS]


def player_matrix(z_long: pd.DataFrame) -> pd.DataFrame:
    """v_player_z rows for one stat window -> one row per player, a z column per
    category (a missing category counts as 0). Columns follow the league's category order."""
    info = z_long.drop_duplicates("player_id").set_index("player_id")[INFO_COLUMNS]
    # The league's categories, in its own order.
    order = list(
        z_long.drop_duplicates("category").sort_values("display_order")["category"]
        if "display_order" in z_long
        else z_long["category"].drop_duplicates()
    )
    z = (
        z_long.pivot_table(index="player_id", columns="category", values="z", aggfunc="first")
        .reindex(columns=order)
        .fillna(0.0)
    )
    players = info.join(z)
    players["is_ir"] = players["is_ir"].fillna(False).astype(bool)
    players["is_free_agent"] = players["is_free_agent"].fillna(False).astype(bool)
    return players


def contribution(players: pd.DataFrame, ids) -> np.ndarray:
    """What these players add to a team total: their z-scores, 0 for anyone on IR."""
    rows = players.loc[list(ids)]
    cols = cat_cols(players)
    return (rows[cols].to_numpy() * ~rows["is_ir"].to_numpy()[:, None]).sum(axis=0)


def team_totals(players: pd.DataFrame) -> pd.DataFrame:
    """Each team's strength per category: the sum of its non-IR players' z-scores."""
    active = players.loc[players["team_id"].notna() & ~players["is_ir"]]
    totals = active.groupby("team_id")[cat_cols(players)].sum()
    totals.index = totals.index.astype(int)
    return totals


def empty_slot_z(z_long: pd.DataFrame) -> pd.Series:
    """The z an empty roster spot would get in each category, for one raw stat window.

    z = 0 is the average pool player, not an empty spot. An empty spot scores 0 (no
    counting stats, and a ratio impact of 0 since it takes no attempts), so its z is
    (0 - mean) / sd, with the mean and spread the same as sql/views/07_v_player_z.sql:
    over the whole pool, ratios scored as num - pool_rate x den, lower-is-better
    flipped. Needed whenever a move changes roster size, or an open spot would look
    as good as an average player."""
    out = {}
    for cat, rows in z_long.groupby("category"):
        num, den = rows["num"].fillna(0), rows["den"].fillna(0)
        if rows["kind"].iloc[0] == "ratio":
            rate = num.sum() / den.sum() if den.sum() else 0.0
            score = np.where(den > 0, num - rate * den, 0.0)
        else:
            score = num.to_numpy()
        if rows["lower_is_better"].iloc[0]:
            score = -score
        sd = score.std()  # population, like STDDEV_POP
        out[cat] = -score.mean() / sd if sd > 0 else 0.0
    return pd.Series(out, dtype=float)
