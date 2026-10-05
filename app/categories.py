"""The league's 9 scoring categories and the one rule for combining them.

Pure pandas, no Streamlit, so the math every page shares is unit-testable. Higher is
better in all 9 -- the league doesn't score turnovers (see docs/step5-analytics.md).
"""

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Category:
    column: str
    label: str
    is_pct: bool = False


CATEGORIES = [
    Category("fg_pct", "FG%", is_pct=True),
    Category("ft_pct", "FT%", is_pct=True),
    Category("fg3m", "3PM"),
    Category("fg3_pct", "3PT%", is_pct=True),
    Category("reb", "REB"),
    Category("ast", "AST"),
    Category("stl", "STL"),
    Category("blk", "BLK"),
    Category("pts", "PTS"),
]
COLUMNS = [c.column for c in CATEGORIES]
LABELS = {c.column: c.label for c in CATEGORIES}

# Each percentage is recomputed from these, never averaged -- 1-for-1 plus 40-for-100
# is 41/101 = 40.6%, not the 70% that averaging 100% and 40% would give.
PCT_PARTS = {"fg_pct": ("fgm", "fga"), "ft_pct": ("ftm", "fta"), "fg3_pct": ("fg3m", "fg3a")}
COUNTING = [c.column for c in CATEGORIES if not c.is_pct]
PART_COLUMNS = sorted({p for parts in PCT_PARTS.values() for p in parts})


def fmt(column: str, value: float | None) -> str:
    if value is None or pd.isna(value):
        return "–"
    if column in PCT_PARTS:
        return f"{value:.3f}".removeprefix("0")  # .471, the way box scores print it
    return f"{value:.1f}"


def totals(rows: pd.DataFrame) -> pd.Series:
    """Sums counting stats and makes/attempts across rows, then recomputes the three
    percentages from the summed parts. A missing stat counts as 0."""
    summed = rows[sorted(set(COUNTING) | set(PART_COLUMNS))].fillna(0).sum()
    out = {}
    for col in COLUMNS:
        if col in PCT_PARTS:
            makes, attempts = PCT_PARTS[col]
            out[col] = summed[makes] / summed[attempts] if summed[attempts] else float("nan")
        else:
            out[col] = summed[col]
    return pd.Series(out, dtype="float64")[COLUMNS]
