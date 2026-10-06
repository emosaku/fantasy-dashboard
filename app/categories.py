"""A league's scoring categories, and the rules every page uses to combine stats.

Categories are data, loaded per league (ingest reads them from the league's ESPN
settings into league_categories and the registry). Each is:
  * count -- one per-game stat (PTS, REB, TO ...): totals add up
  * ratio -- one total over another (FG% = FGM / FGA, A/TO = AST / TO): recomputed
             from the summed totals, never averaged -- 1-for-1 plus 40-for-100 is
             41/101 = 40.6%, not the 70% averaging gives
and may be lower-is-better (turnovers). `score()` flips those so "higher wins" holds
everywhere comparisons happen. A category's key is ESPN's abbreviation, which is
also how pages label it.

Pure pandas, no Streamlit: unit-tested.
"""

import math
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Category:
    key: str
    kind: str  # "count" | "ratio"
    num: str
    den: str | None = None
    lower_is_better: bool = False

    @property
    def label(self) -> str:
        return self.key


def from_records(records) -> list[Category]:
    """Categories from registry / league_categories rows, in the league's order."""
    rows = sorted(records, key=lambda r: r.get("display_order", 0))
    return [
        Category(
            key=r["category"],
            kind=r["kind"],
            num=r["num_stat"],
            den=r.get("den_stat") or None,
            lower_is_better=bool(r.get("lower_is_better", False)),
        )
        for r in rows
    ]


def keys(cats: list[Category]) -> list[str]:
    return [c.key for c in cats]


def by_key(cats: list[Category]) -> dict[str, Category]:
    return {c.key: c for c in cats}


def score(cat: Category, value: float) -> float:
    """Comparable value: higher always better."""
    return -value if cat.lower_is_better else value


def stats_needed(cats: list[Category]) -> list[str]:
    """Per-game stats these categories are built from."""
    return sorted({c.num for c in cats} | {c.den for c in cats if c.den})


def fmt(cat: Category, value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)) or pd.isna(value):
        return "–"
    if cat.kind == "ratio" and cat.key.endswith("%"):
        return f"{value:.3f}".removeprefix("0")  # .471, the way box scores print it
    if cat.kind == "ratio":
        return f"{value:.2f}"  # A/TO
    return f"{value:.1f}"


def totals(rows: pd.DataFrame, cats: list[Category]) -> pd.Series:
    """Combine stat lines (one row each, a column per stat) into one value per
    category: counts summed, ratios from the summed totals. A missing stat counts
    as 0; a ratio with nothing below the line is NaN."""
    need = stats_needed(cats)
    summed = rows.reindex(columns=need).fillna(0).sum()
    out = {}
    for c in cats:
        if c.kind == "ratio":
            out[c.key] = summed[c.num] / summed[c.den] if summed[c.den] else float("nan")
        else:
            out[c.key] = summed[c.num]
    return pd.Series(out, dtype="float64")[keys(cats)]


# The original league's categories, for tests and as an example.
NINE_CAT_NO_TO = [
    Category("FG%", "ratio", "FGM", "FGA"),
    Category("FT%", "ratio", "FTM", "FTA"),
    Category("3PM", "count", "3PM"),
    Category("3PT%", "ratio", "3PM", "3PA"),
    Category("REB", "count", "REB"),
    Category("AST", "count", "AST"),
    Category("STL", "count", "STL"),
    Category("BLK", "count", "BLK"),
    Category("PTS", "count", "PTS"),
]
