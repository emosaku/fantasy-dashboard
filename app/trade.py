"""Trade Analyzer math -- the one place the app computes instead of plotting a view.

Which players are traded changes on every click, so there's nothing for SQL to
precompute: v_team_roster_stats supplies each player's per-game line once, and the
before/after/delta happens here, live. Pure pandas, so it's unit-testable.

Roster totals leave out players in the IR slot, the same rule v_roster_strength
uses -- they aren't playing, so trading one away (or for one) changes nothing today.
"""

import pandas as pd

from categories import COLUMNS, totals


def roster_totals(players: pd.DataFrame) -> pd.Series:
    """Per-game output of a roster: summed per-game stats, recomputed percentages."""
    return totals(players.loc[players["lineup_slot"] != "IR"])


def trade_impact(
    roster: pd.DataFrame, sending_ids: list[int], receiving: pd.DataFrame
) -> pd.DataFrame:
    """Before/after/delta per category for one side of a trade.

    roster: that side's current players. sending_ids: player_ids leaving it.
    receiving: the other side's player rows coming in.
    """
    before = roster_totals(roster)
    after_roster = pd.concat(
        [roster.loc[~roster["player_id"].isin(sending_ids)], receiving], ignore_index=True
    )
    after = roster_totals(after_roster)
    return pd.DataFrame({"before": before, "after": after, "delta": after - before}).loc[COLUMNS]
