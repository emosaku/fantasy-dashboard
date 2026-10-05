"""Turns v_player_z rows into the two frames the analysis works on."""

import numpy as np
import pandas as pd

from categories import COLUMNS

INFO_COLUMNS = ["player_name", "team_id", "is_free_agent", "is_ir", "injury_status", "position"]


def player_matrix(z_long: pd.DataFrame) -> pd.DataFrame:
    """v_player_z rows for one stat window -> one row per player, a z column per
    category (a missing category counts as 0)."""
    info = z_long.drop_duplicates("player_id").set_index("player_id")[INFO_COLUMNS]
    z = (
        z_long.pivot_table(index="player_id", columns="category", values="z", aggfunc="first")
        .reindex(columns=COLUMNS)
        .fillna(0.0)
    )
    players = info.join(z)
    players["is_ir"] = players["is_ir"].fillna(False).astype(bool)
    players["is_free_agent"] = players["is_free_agent"].fillna(False).astype(bool)
    return players


def contribution(players: pd.DataFrame, ids) -> np.ndarray:
    """What these players add to a team total: their z-scores, 0 for anyone on IR."""
    rows = players.loc[list(ids)]
    return (rows[COLUMNS].to_numpy() * ~rows["is_ir"].to_numpy()[:, None]).sum(axis=0)


def team_totals(players: pd.DataFrame) -> pd.DataFrame:
    """Each team's strength per category: the sum of its non-IR players' z-scores."""
    active = players.loc[players["team_id"].notna() & ~players["is_ir"]]
    totals = active.groupby("team_id")[COLUMNS].sum()
    totals.index = totals.index.astype(int)
    return totals
