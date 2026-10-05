"""Compare page math: one stat line per team for a week or the season, z-scored
across the league. Pure pandas, so it's unit-testable without BigQuery.

v_team_week_cats holds raw weekly values; z-scoring them happens here because the
period being compared (one week, or the season) is a page control, not something a
view can fix in advance.
"""

import pandas as pd

from categories import COLUMNS, COUNTING, PART_COLUMNS, totals


def period_lines(weeks: pd.DataFrame, week: int | None) -> pd.DataFrame:
    """One row per team_id with the 9 categories.

    week=None is the season: counting stats become per-week averages (teams can
    have played different numbers of weeks), and percentages are recomputed from
    season makes/attempts rather than averaged week to week.
    """
    if week is not None:
        return weeks.loc[weeks["matchup_period"] == week].set_index("team_id")[COLUMNS]

    def season_line(team_weeks: pd.DataFrame) -> pd.Series:
        line = totals(team_weeks)
        line[COUNTING] = line[COUNTING] / len(team_weeks)
        return line

    cols = sorted(set(COUNTING) | set(PART_COLUMNS))
    return weeks.groupby("team_id")[cols].apply(season_line)[COLUMNS]


def zscores(lines: pd.DataFrame) -> pd.DataFrame:
    """How many league standard deviations each team sits above or below the
    league average, per category. NaN where every team is equal (std 0)."""
    std = lines.std(ddof=0).replace(0, float("nan"))
    return (lines - lines.mean()) / std


def head_to_head(a: pd.Series, b: pd.Series) -> tuple[int, int, int]:
    """(a's wins, b's wins, ties) across the 9 categories. A NaN compares as a tie."""
    wins = int((a > b).sum())
    losses = int((a < b).sum())
    return wins, losses, len(COLUMNS) - wins - losses
