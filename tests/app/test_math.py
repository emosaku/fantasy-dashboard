"""The app's own math: category totals and formatting, Compare's season lines,
z-scores and head-to-head, and the Trade Analyzer's before/after/delta. Every
expected value is worked out by hand. Categories are data: the original league's
nine, plus turnovers (lower wins) and A/TO (a ratio that isn't a percentage)."""

import math

import pandas as pd
import pytest

from categories import (
    NINE_CAT_NO_TO,
    Category,
    by_key,
    fmt,
    from_records,
    keys,
    stats_needed,
    totals,
)
from compare import head_to_head, period_lines, scores, zscores
from trade import trade_impact, wide_lines

TO = Category("TO", "count", "TO", lower_is_better=True)
ATO = Category("A/TO", "ratio", "AST", "TO")
CATS = [*NINE_CAT_NO_TO, TO, ATO]
C = by_key(CATS)


def player(pid, slot="BE", **stats):
    base = dict.fromkeys(stats_needed(CATS), 0.0)
    return {"player_id": pid, "lineup_slot": slot, **base, **stats}


def test_from_records_orders_by_display_order_and_reads_direction():
    cats = from_records(
        [
            {"category": "TO", "kind": "count", "num_stat": "TO", "den_stat": None,
             "lower_is_better": True, "display_order": 1},
            {"category": "FG%", "kind": "ratio", "num_stat": "FGM", "den_stat": "FGA",
             "lower_is_better": False, "display_order": 0},
        ]
    )  # fmt: skip
    assert keys(cats) == ["FG%", "TO"]
    assert cats[1].lower_is_better and cats[0].den == "FGA"


def test_totals_recomputes_ratios_from_the_two_totals():
    # 1-for-1 and 40-for-100: 41/101, not the 70% that averaging would give.
    rows = pd.DataFrame(
        [player(1, FGM=1, FGA=1, PTS=2, AST=4, TO=2), player(2, FGM=40, FGA=100, PTS=80, AST=2)]
    )
    line = totals(rows, CATS)
    assert line["FG%"] == pytest.approx(41 / 101)
    assert line["PTS"] == 82
    assert line["A/TO"] == pytest.approx(6 / 2)
    assert math.isnan(line["FT%"])  # 0 attempts: no percentage, not 0%


def test_totals_treats_missing_stats_as_zero():
    rows = pd.DataFrame([player(1, **{"3PM": 2, "3PA": 5}), player(2, **{"3PM": None})])
    line = totals(rows, CATS)
    assert line["3PM"] == 2
    assert line["3PT%"] == pytest.approx(0.4)


def test_fmt():
    assert fmt(C["FG%"], 0.4712) == ".471"
    assert fmt(C["A/TO"], 1.849) == "1.85"
    assert fmt(C["PTS"], 112.25) == "112.2"
    assert fmt(C["PTS"], None) == "–"


def week_rows(team, week, **values):
    """v_team_week_cats-shaped rows (long): values maps category -> value, and
    num/den pairs as e.g. FG%=(made, attempted)."""
    rows = []
    for key, v in values.items():
        num, den = v if isinstance(v, tuple) else (None, None)
        value = num / den if isinstance(v, tuple) else v
        rows.append(
            {"team_id": team, "matchup_period": week, "category": key, "num": num,
             "den": den, "value": value}
        )  # fmt: skip
    return rows


def test_season_line_averages_counts_and_pools_ratios():
    cats = [C["PTS"], C["FG%"]]
    weeks = pd.DataFrame(
        week_rows(1, 1, PTS=100, **{"FG%": (10, 20)})
        + week_rows(1, 2, PTS=140, **{"FG%": (30, 40)})
    )
    line = period_lines(weeks, cats, None).loc[1]
    assert line["PTS"] == 120  # per-week average
    assert line["FG%"] == pytest.approx(40 / 60)  # not (50% + 75%) / 2


def test_single_week_line_is_that_week_unchanged():
    weeks = pd.DataFrame(week_rows(1, 1, PTS=100) + week_rows(1, 2, PTS=140))
    assert period_lines(weeks, [C["PTS"]], 2).loc[1, "PTS"] == 140


def test_zscores_flip_lower_is_better():
    lines = pd.DataFrame(
        {"PTS": [100.0, 110.0, 120.0], "REB": [40.0, 40.0, 40.0], "TO": [10.0, 12.0, 14.0]}
    )
    z = zscores(lines, [C["PTS"], C["REB"], TO])
    assert z["PTS"].tolist() == pytest.approx([-1.2247, 0, 1.2247], abs=1e-4)
    assert z["TO"].tolist() == pytest.approx([1.2247, 0, -1.2247], abs=1e-4)  # fewest is best
    assert z["REB"].isna().all()  # everyone equal: no spread to measure against


def test_head_to_head_uses_scores_and_counts_nan_as_tie():
    cats = [C["PTS"], C["REB"], C["FG%"], TO]
    lines = pd.DataFrame(
        {"PTS": [5.0, 4.0], "REB": [1.0, 2.0], "FG%": [float("nan"), 0.5], "TO": [3.0, 9.0]}
    )
    s = scores(lines, cats)
    assert head_to_head(s.loc[0], s.loc[1]) == (2, 1, 1)  # PTS and fewer TO; REB lost


def test_trade_impact_both_directions():
    mine = pd.DataFrame(
        [
            player(1, PTS=20, REB=5, FGM=8, FGA=16, TO=2),
            player(2, PTS=10, REB=10, FGM=4, FGA=8, TO=1),
            player(3, slot="IR", PTS=30, FGM=12, FGA=20),  # on IR: never counted
        ]
    )
    incoming = pd.DataFrame([player(9, PTS=15, REB=2, FGM=6, FGA=10, TO=4)])

    impact = trade_impact(mine, sending_ids=[2], receiving=incoming, cats=CATS)

    assert impact.loc["PTS", ["before", "after", "delta"]].tolist() == [30, 35, 5]
    assert impact.loc["REB", ["before", "after", "delta"]].tolist() == [15, 7, -8]
    assert impact.at["FG%", "before"] == pytest.approx(12 / 24)
    assert impact.at["FG%", "after"] == pytest.approx(14 / 26)
    assert impact.at["TO", "delta"] == 3 and impact.at["TO", "better"] == -3  # worse
    assert list(impact.index) == keys(CATS)


def test_trading_away_an_ir_player_changes_nothing():
    mine = pd.DataFrame([player(1, PTS=20), player(3, slot="IR", PTS=30)])
    impact = trade_impact(mine, sending_ids=[3], receiving=mine.iloc[0:0], cats=CATS)
    assert impact.loc["PTS", "delta"] == 0


def test_wide_lines_pivots_the_long_pool():
    pool = pd.DataFrame(
        [
            {"player_id": 1, "team_id": 4, "player_name": "A", "lineup_slot": "PG",
             "injury_status": "ACTIVE", "expected_return_date": None, "stat": s, "value": v}
            for s, v in (("PTS", 20.0), ("TO", 3.0))
        ]
    )  # fmt: skip
    wide = wide_lines(pool)
    assert wide.loc[0, "PTS"] == 20.0 and wide.loc[0, "TO"] == 3.0
    assert wide.loc[0, "player_id"] == 1 and wide.loc[0, "lineup_slot"] == "PG"
