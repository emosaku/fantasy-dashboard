"""Waiver wire: every "add this free agent, drop that player" pair, ranked by the
change in my E. Free agents listed OUT are skipped; IR players aren't dropped (they
don't count toward totals anyway). Ties in E are broken by the change in my
team-specific player value, v(add) - v(drop)."""

import numpy as np
import pandas as pd

from analysis.objective import category_wins
from analysis.weights import player_values, punts
from categories import COLUMNS


def rank_waiver_moves(
    players: pd.DataFrame, totals: pd.DataFrame, me: int, weights: pd.DataFrame, top: int = 10
) -> pd.DataFrame:
    free_agents = players.loc[players["is_free_agent"] & (players["injury_status"] != "OUT")]
    mine = players.loc[(players["team_id"] == me) & ~players["is_ir"]]
    if free_agents.empty or mine.empty:
        return pd.DataFrame()

    row = totals.loc[me].to_numpy()
    others = totals.drop(me).to_numpy()
    zf, zd = free_agents[COLUMNS].to_numpy(), mine[COLUMNS].to_numpy()

    after = row + zf[:, None, :] - zd[None, :, :]  # free agent x drop x category
    cat = category_wins(after.reshape(-1, len(COLUMNS)), others) - category_wins(row, others)
    cat[:, np.isin(COLUMNS, punts(weights))] = 0.0

    vf = player_values(free_agents, weights).to_numpy()
    vd = player_values(mine, weights).to_numpy()
    f_idx, d_idx = np.divmod(np.arange(len(cat)), len(mine))
    moves = pd.DataFrame(
        {
            "add_id": free_agents.index.to_numpy()[f_idx],
            "add_name": free_agents["player_name"].to_numpy()[f_idx],
            "injury_status": free_agents["injury_status"].to_numpy()[f_idx],
            "drop_id": mine.index.to_numpy()[d_idx],
            "drop_name": mine["player_name"].to_numpy()[d_idx],
            "dE": cat.sum(1),
            "dv": vf[f_idx] - vd[d_idx],
            **{f"dE_{c}": cat[:, i] for i, c in enumerate(COLUMNS)},
            **{f"dz_{c}": (zf[f_idx] - zd[d_idx])[:, i] for i, c in enumerate(COLUMNS)},
        }
    )
    return moves.sort_values(["dE", "dv"], ascending=False).head(top).reset_index(drop=True)
