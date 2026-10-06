"""Compare page math: one line per team for a week or the season, z-scored across the
league. Pure pandas, so it's unit-testable without BigQuery.

Input is v_team_week_cats (long: team x week x category, with the ratio categories'
two totals). Comparisons use each category's score (lower-is-better flipped), so a
team "wins" turnovers by having fewer.
"""

import pandas as pd

from categories import Category, keys, score


def period_lines(weeks: pd.DataFrame, cats: list[Category], week: int | None) -> pd.DataFrame:
    """One row per team_id, a column per category (the values shown).

    week=None is the season: count categories become per-week averages (teams can
    have played different numbers of weeks), and ratios are recomputed from the
    season's two totals rather than averaged week to week.
    """
    rows = weeks if week is None else weeks.loc[weeks["matchup_period"] == week]
    out = {}
    for cat in cats:
        one = rows.loc[rows["category"] == cat.key]
        by_team = one.groupby("team_id")
        if week is not None:
            out[cat.key] = by_team["value"].first()
        elif cat.kind == "ratio" and one["den"].notna().any():
            sums = by_team[["num", "den"]].sum(min_count=1)
            out[cat.key] = sums["num"] / sums["den"].where(sums["den"] != 0)
        else:
            out[cat.key] = by_team["value"].mean()
    return pd.DataFrame(out).reindex(columns=keys(cats)).astype("float64")


def scores(lines: pd.DataFrame, cats: list[Category]) -> pd.DataFrame:
    """Values -> comparable scores: higher always better."""
    return pd.DataFrame({c.key: score(c, lines[c.key]) for c in cats}, index=lines.index)


def zscores(lines: pd.DataFrame, cats: list[Category]) -> pd.DataFrame:
    """How many league standard deviations each team sits above (better) or below
    the league average, per category. NaN where every team is equal (std 0)."""
    s = scores(lines, cats)
    std = s.std(ddof=0).replace(0, float("nan"))
    return (s - s.mean()) / std


def head_to_head(a: pd.Series, b: pd.Series) -> tuple[int, int, int]:
    """(a's wins, b's wins, ties) across the categories, from scores. A NaN ties."""
    wins = int((a > b).sum())
    losses = int((a < b).sum())
    return wins, losses, len(a) - wins - losses
