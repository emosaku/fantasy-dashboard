"""Player rankings: every pool player ranked in each of the 9 categories and overall,
for the Player Rankings page.

Built on v_player_z (one stat window): a player's category rank is his place among
the whole pool -- every rostered player plus the top free agents -- by z-score in
that category (1 = best; ties share a rank). Ranking by z rather than raw value
matters for FG%/FT%/3PT%: their z is volume-weighted, so a 60% shooter on two
attempts doesn't outrank a 50% shooter on twenty. Overall is the sum of the 9 z-scores,
ranked the same way. Ranks are computed over the whole pool before any filtering, so
a filtered view still shows league-wide ranks.
"""

import pandas as pd

from categories import COLUMNS

INFO = ["player_name", "team_id", "is_free_agent", "is_ir", "injury_status", "position"]


def player_rankings(z_long: pd.DataFrame) -> pd.DataFrame:
    """One row per player: info columns; {category}_value, {category}_z and
    {category}_rank for each category; total_z and overall_rank. Sorted by overall."""
    info = z_long.drop_duplicates("player_id").set_index("player_id")[INFO]
    z = z_long.pivot_table(index="player_id", columns="category", values="z", aggfunc="first")
    value = z_long.pivot_table(
        index="player_id", columns="category", values="value", aggfunc="first"
    )
    z = z.reindex(columns=COLUMNS).fillna(0.0)
    value = value.reindex(columns=COLUMNS)

    ranks = z.rank(ascending=False, method="min").astype(int)
    total = z.sum(axis=1)
    out = info.join(
        pd.concat(
            [
                value.add_suffix("_value"),
                z.add_suffix("_z"),
                ranks.add_suffix("_rank"),
            ],
            axis=1,
        )
    )
    out["total_z"] = total
    out["overall_rank"] = total.rank(ascending=False, method="min").astype(int)
    return out.sort_values(["overall_rank", "player_name"])
