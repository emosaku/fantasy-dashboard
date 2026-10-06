"""Per-game totals before and after a deal (the Mock trade tab's last table).

v_player_pool is long (player x stat window x stat); `wide_lines` turns it into one
row per player with a column per stat, and categories.totals() combines a roster's
rows into the league's categories: counts summed, ratios from the summed totals.
Roster totals leave out players in the IR slot. Pure pandas, so it's unit-testable.
"""

import pandas as pd

from categories import Category, keys, score, totals

INFO = ["team_id", "player_name", "lineup_slot", "injury_status", "expected_return_date"]


def wide_lines(pool: pd.DataFrame) -> pd.DataFrame:
    """Long per-game rows for one stat window -> one row per player (player_id kept as
    a column), info columns plus a column per stat."""
    if pool.empty:
        return pd.DataFrame(columns=["player_id", *INFO])
    stats = pool.pivot_table(index="player_id", columns="stat", values="value", aggfunc="first")
    info = pool.drop_duplicates("player_id").set_index("player_id")
    info = info[[c for c in INFO if c in info]]
    return info.join(stats).reset_index()


def roster_totals(players: pd.DataFrame, cats: list[Category]) -> pd.Series:
    return totals(players.loc[players["lineup_slot"] != "IR"], cats)


def trade_impact(
    roster: pd.DataFrame, sending_ids: list[int], receiving: pd.DataFrame, cats: list[Category]
) -> pd.DataFrame:
    """Before/after/delta per category for one side of a trade, plus `better`: the
    delta's sign as a gain (positive = better, whichever way the category runs)."""
    before = roster_totals(roster, cats)
    after_roster = pd.concat(
        [roster.loc[~roster["player_id"].isin(sending_ids)], receiving], ignore_index=True
    )
    after = roster_totals(after_roster, cats)
    delta = after - before
    better = pd.Series({c.key: score(c, delta[c.key]) for c in cats}, dtype="float64")
    out = pd.DataFrame({"before": before, "after": after, "delta": delta, "better": better})
    return out.loc[keys(cats)]
