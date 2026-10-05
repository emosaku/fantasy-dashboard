"""The app's own math: category totals, Compare's season lines and z-scores, and the
Trade Analyzer's before/after/delta. Every expected value is worked out by hand."""

import math

import pandas as pd
import pytest

from categories import COLUMNS, fmt, totals
from compare import head_to_head, period_lines, zscores
from trade import trade_impact


def player(pid, slot="BE", **stats):
    base = dict.fromkeys(["fgm", "fga", "ftm", "fta", "fg3m", "fg3a"], 0.0)
    base |= dict.fromkeys(["reb", "ast", "stl", "blk", "pts"], 0.0)
    return {"player_id": pid, "lineup_slot": slot, **base, **stats}


def test_totals_recomputes_percentages_from_makes_and_attempts():
    # 1-for-1 and 40-for-100: 41/101, not the 70% that averaging would give.
    rows = pd.DataFrame([player(1, fgm=1, fga=1, pts=2), player(2, fgm=40, fga=100, pts=80)])
    line = totals(rows)
    assert line["fg_pct"] == pytest.approx(41 / 101)
    assert line["pts"] == 82
    assert math.isnan(line["ft_pct"])  # 0 attempts: no percentage, not 0%


def test_totals_treats_missing_stats_as_zero():
    rows = pd.DataFrame([player(1, fg3m=2, fg3a=5), player(2, fg3m=None, fg3a=None)])
    line = totals(rows)
    assert line["fg3m"] == 2
    assert line["fg3_pct"] == pytest.approx(0.4)


def test_fmt():
    assert fmt("fg_pct", 0.4712) == ".471"
    assert fmt("pts", 112.25) == "112.2"
    assert fmt("pts", None) == "–"


def week_row(team, week, **stats):
    return {"team_id": team, "matchup_period": week, **player(0, **stats)}


def test_season_line_averages_counting_stats_and_pools_percentages():
    weeks = pd.DataFrame(
        [
            week_row(1, 1, pts=100, fgm=10, fga=20),  # 50%
            week_row(1, 2, pts=140, fgm=30, fga=40),  # 75%
        ]
    )
    line = period_lines(weeks, None).loc[1]
    assert line["pts"] == 120  # per-week average
    assert line["fg_pct"] == pytest.approx(40 / 60)  # not (50% + 75%) / 2


def test_single_week_line_is_that_week_unchanged():
    weeks = pd.DataFrame([week_row(1, 1, pts=100), week_row(1, 2, pts=140)])
    weeks["fg_pct"] = weeks["ft_pct"] = weeks["fg3_pct"] = None
    assert period_lines(weeks, 2).loc[1, "pts"] == 140


def test_zscores():
    lines = pd.DataFrame({"pts": [100.0, 110.0, 120.0], "reb": [40.0, 40.0, 40.0]})
    z = zscores(lines)
    assert z["pts"].tolist() == pytest.approx([-1.2247, 0, 1.2247], abs=1e-4)
    assert z["reb"].isna().all()  # everyone equal: no spread to measure against


def test_head_to_head_counts_nan_as_tie():
    a = dict.fromkeys(COLUMNS, 1.0) | {"pts": 5.0, "fg_pct": float("nan")}
    b = dict.fromkeys(COLUMNS, 1.0) | {"pts": 4.0, "reb": 2.0}
    assert head_to_head(pd.Series(a), pd.Series(b)) == (1, 1, 7)


def test_trade_impact_both_directions():
    mine = pd.DataFrame(
        [
            player(1, pts=20, reb=5, fgm=8, fga=16),
            player(2, pts=10, reb=10, fgm=4, fga=8),
            player(3, slot="IR", pts=30, fgm=12, fga=20),  # on IR: never counted
        ]
    )
    incoming = pd.DataFrame([player(9, pts=15, reb=2, fgm=6, fga=10)])

    impact = trade_impact(mine, sending_ids=[2], receiving=incoming)

    assert impact.loc["pts"].tolist() == [30, 35, 5]
    assert impact.loc["reb"].tolist() == [15, 7, -8]
    assert impact.at["fg_pct", "before"] == pytest.approx(12 / 24)
    assert impact.at["fg_pct", "after"] == pytest.approx(14 / 26)
    assert list(impact.index) == COLUMNS


def test_trading_away_an_ir_player_changes_nothing():
    mine = pd.DataFrame([player(1, pts=20), player(3, slot="IR", pts=30)])
    impact = trade_impact(mine, sending_ids=[3], receiving=mine.iloc[0:0])
    assert impact.loc["pts", "delta"] == 0
