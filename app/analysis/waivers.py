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
    roster = players.index[players["team_id"] == me]
    return rank_pickups(players, totals, me, weights, roster, top=top)


def rank_pickups(
    players: pd.DataFrame,
    totals: pd.DataFrame,
    me: int,
    weights: pd.DataFrame,
    roster,
    exclude=(),
    add_only: bool = False,
    top: int = 10,
    empty=None,
) -> pd.DataFrame:
    """Free-agent pickups for `roster` (my player ids -- after a mock trade, the
    roster that trade leaves me), against `totals` (the team totals at that point).
    add_only: rank plain adds, for a roster with an open spot; otherwise every
    add-and-drop pair. `exclude`: free agents already in the move. Same columns as
    rank_waiver_moves; drop_id is None for a plain add. empty: the z of an empty
    spot (pool.empty_slot_z) -- a plain add fills one, so it gains z(add) - z(empty);
    without it the add is compared with an average player."""
    pool = players.loc[
        players["is_free_agent"]
        & (players["injury_status"] != "OUT")
        & ~players.index.isin(list(exclude))
    ]
    mine = players.loc[players.index.isin(list(roster)) & ~players["is_ir"]]
    if pool.empty or (mine.empty and not add_only):
        return pd.DataFrame()

    row = totals.loc[me].to_numpy()
    others = totals.drop(me).to_numpy()
    cols = COLUMNS
    zf = pool[cols].to_numpy()
    vf = player_values(pool, weights).to_numpy()
    if add_only:
        zd = (
            np.zeros((1, len(cols)))
            if empty is None
            else empty.reindex(cols).fillna(0).to_numpy()[None, :]
        )
        drop_ids, drop_names, vd = np.array([None]), np.array([""]), np.zeros(1)
    else:
        zd = mine[cols].to_numpy()
        drop_ids, drop_names = mine.index.to_numpy(), mine["player_name"].to_numpy()
        vd = player_values(mine, weights).to_numpy()

    after = row + zf[:, None, :] - zd[None, :, :]  # free agent x drop x category
    cat = category_wins(after.reshape(-1, len(COLUMNS)), others) - category_wins(row, others)
    cat[:, np.isin(COLUMNS, punts(weights))] = 0.0

    f_idx, d_idx = np.divmod(np.arange(len(cat)), len(zd))
    moves = pd.DataFrame(
        {
            "add_id": pool.index.to_numpy()[f_idx],
            "add_name": pool["player_name"].to_numpy()[f_idx],
            "injury_status": pool["injury_status"].to_numpy()[f_idx],
            "drop_id": drop_ids[d_idx],
            "drop_name": drop_names[d_idx],
            "dE": cat.sum(1),
            "dv": vf[f_idx] - vd[d_idx],
            **{f"dE_{c}": cat[:, i] for i, c in enumerate(COLUMNS)},
            **{f"dz_{c}": (zf[f_idx] - zd[d_idx])[:, i] for i, c in enumerate(COLUMNS)},
        }
    )
    return moves.sort_values(["dE", "dv"], ascending=False).head(top).reset_index(drop=True)
