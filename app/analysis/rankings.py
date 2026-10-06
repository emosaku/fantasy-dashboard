"""Player rankings: every pool player ranked in each of the league's categories and
overall, for the Player Rankings page.

Built on v_player_z (one stat window): a player's category rank is his place among
the whole pool -- every rostered player plus the top free agents -- by z-score in
that category (1 = best; ties share a rank). z already points the right way for
lower-is-better categories (fewer turnovers = higher z), and for ratio categories it
is volume-weighted, so a 60% shooter on two attempts doesn't outrank a 50% shooter on
twenty. Overall is the sum of the z-scores, ranked the same way. Ranks are computed
over the whole pool before any filtering, so a filtered view still shows league-wide
ranks.
"""

import pandas as pd

from analysis.pool import INFO_COLUMNS


def category_order(z_long: pd.DataFrame) -> list[str]:
    return list(z_long.drop_duplicates("category").sort_values("display_order")["category"])


def player_rankings(z_long: pd.DataFrame) -> pd.DataFrame:
    """One row per player: info columns; {category}_value, {category}_z and
    {category}_rank for each category; total_z and overall_rank. Sorted by overall."""
    order = category_order(z_long)
    info = z_long.drop_duplicates("player_id").set_index("player_id")[INFO_COLUMNS]
    z = z_long.pivot_table(index="player_id", columns="category", values="z", aggfunc="first")
    value = z_long.pivot_table(
        index="player_id", columns="category", values="value", aggfunc="first"
    )
    z = z.reindex(columns=order).fillna(0.0)
    value = value.reindex(columns=order)

    ranks = z.rank(ascending=False, method="min").astype(int)
    total = z.sum(axis=1)
    out = info.join(
        pd.concat(
            [value.add_suffix("_value"), z.add_suffix("_z"), ranks.add_suffix("_rank")],
            axis=1,
        )
    )
    out["total_z"] = total
    out["overall_rank"] = total.rank(ascending=False, method="min").astype(int)
    return out.sort_values(["overall_rank", "player_name"])
