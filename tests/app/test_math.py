"""The app's own math: category totals, Compare's season lines and z-scores,
Compare's Players mode, and the Trade Analyzer's before/after/delta. Every expected
value is worked out by hand."""

import math

import pandas as pd
import pytest

from analysis.rankings import player_rankings
from categories import COLUMNS, fmt, totals
from compare import (
    baseline_id,
    head_to_head,
    head_to_head_verdict,
    period_lines,
    player_compare_frame,
    pool_window_frame,
    position_baseline,
    season_totals,
    starter_ids,
    zscores,
)
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


# --- Compare: Players mode ----------------------------------------------------------


def z_row(pid, name, team, window, zs, values=None):
    """v_player_z-shaped rows for one player in one stat window: zs maps category ->
    z (others 0); values defaults to the same number as z when not given."""
    return [
        {
            "player_id": pid,
            "player_name": name,
            "team_id": team,
            "is_free_agent": team is None,
            "is_ir": False,
            "injury_status": "ACTIVE",
            "position": "G",
            "stat_window": window,
            "category": c,
            "z": zs.get(c, 0.0),
            "value": (values or zs).get(c, 0.0),
        }
        for c in COLUMNS
    ]


def pool_row(pid, window, **stats):
    base = dict.fromkeys(["fgm", "fga", "ftm", "fta", "fg3m", "fg3a"], 0.0)
    return {"player_id": pid, "stat_window": window, **base, **stats}


def player_pool_fixture():
    z = pd.DataFrame(
        z_row(1, "Star", 10, "season", {"pts": 2.0, "fg_pct": 1.5}, {"pts": 28.0, "fg_pct": 0.52})
        + z_row(
            2,
            "Sharpshooter",
            11,
            "season",
            {"fg_pct": -0.5, "fg3m": 2.0},
            {"fg_pct": 0.60, "fg3m": 3.5},
        )  # fmt: skip
        + z_row(3, "Free agent", None, "season", {"pts": 1.0}, {"pts": 20.0})
        + z_row(1, "Star", 10, "projected", {"pts": 1.0}, {"pts": 24.0})
    )
    pool = pd.DataFrame(
        [
            pool_row(1, "season", fgm=13.0, fga=25.0),
            pool_row(2, "season", fgm=3.0, fga=5.0),
            pool_row(3, "season"),
        ]
    )
    return z, pool


def test_player_compare_frame_matches_player_rankings_for_the_same_window():
    z, pool = player_pool_fixture()
    frame = player_compare_frame(z, pool, [1, 2], "season")
    ranks = player_rankings(z.loc[z["stat_window"] == "season"])  # already indexed by player_id
    for pid in (1, 2):
        for col in COLUMNS:
            row = frame.loc[(frame["player_id"] == pid) & (frame["category"] == col)].iloc[0]
            assert row["z"] == pytest.approx(ranks.at[pid, f"{col}_z"])
            assert row["rank"] == ranks.at[pid, f"{col}_rank"]


def test_player_compare_frame_loads_both_rostered_and_free_agent():
    z, pool = player_pool_fixture()
    frame = player_compare_frame(z, pool, [1, 3], "season")
    assert set(frame["player_id"]) == {1, 3}
    assert (
        frame.loc[(frame["player_id"] == 3) & (frame["category"] == "pts"), "value"].iloc[0] == 20.0
    )


def test_player_compare_frame_percentage_rows_carry_makes_and_attempts():
    z, pool = player_pool_fixture()
    frame = player_compare_frame(z, pool, [1, 2], "season").set_index(["player_id", "category"])
    assert frame.loc[(1, "fg_pct"), "num":"den"].tolist() == [13.0, 25.0]
    assert frame.loc[(2, "fg_pct"), "num":"den"].tolist() == [3.0, 5.0]
    assert math.isnan(frame.loc[(1, "pts"), "num"])  # not a percentage: no makes/attempts


def test_player_compare_frame_respects_the_chosen_window():
    z, pool = player_pool_fixture()
    frame = player_compare_frame(z, pool, [1], "projected").set_index("category")
    assert frame.loc["pts", "value"] == 24.0  # the projected row, not season's 28.0


def test_verdict_counts_by_z_so_volume_beats_raw_percentage():
    # Sharpshooter's raw FG% (60%) beats Star's (52%), but on volume (25 vs 5
    # attempts) Star's z is higher -- the verdict must follow z, not the percentage.
    z, pool = player_pool_fixture()
    frame = player_compare_frame(z, pool, [1, 2], "season")
    verdict = head_to_head_verdict(frame, {1: "Star", 2: "Sharpshooter"})
    assert verdict.startswith("Star wins")
    assert (
        "FG%" not in verdict.split(";")[0]
    )  # FG% is Star's category, not his win margin's complement
    assert "3PM" in verdict  # Sharpshooter's actual win


def test_verdict_handles_a_tie():
    z = pd.DataFrame(z_row(1, "A", 10, "season", {}) + z_row(2, "B", 11, "season", {}))
    pool = pd.DataFrame([pool_row(1, "season"), pool_row(2, "season")])
    frame = player_compare_frame(z, pool, [1, 2], "season")
    assert head_to_head_verdict(frame, {1: "A", 2: "B"}) == "A and B are even: 0 categories each."


def test_verdict_requires_exactly_two_players():
    z, pool = player_pool_fixture()
    frame = player_compare_frame(z, pool, [1, 2, 3], "season")
    with pytest.raises(ValueError, match="exactly 2"):
        head_to_head_verdict(frame, {1: "Star", 2: "Sharpshooter", 3: "Free agent"})


def test_blended_percentages_fall_back_to_season_then_projected_pool_rows():
    # v_player_pool has no 'blended' rows of its own; a player with a season line
    # uses it, one with only a projected line falls back to that.
    pool = pd.DataFrame(
        [
            pool_row(1, "season", fgm=10.0, fga=20.0),
            pool_row(1, "projected", fgm=99.0, fga=99.0),  # must be ignored: season exists
            pool_row(2, "projected", fgm=4.0, fga=8.0),  # no season row: falls back
        ]
    )
    resolved = pool_window_frame(pool, "blended").set_index("player_id")
    assert resolved.loc[1, ["fgm", "fga"]].tolist() == [10.0, 20.0]
    assert resolved.loc[2, ["fgm", "fga"]].tolist() == [4.0, 8.0]


# --- Players mode: position baseline and season totals ------------------------------


def roster_rows(pid, position, team, slot, zs, values=None):
    rows = z_row(pid, f"P{pid}", team, "season", zs, values)
    for r in rows:
        r["position"], r["lineup_slot"] = position, slot
    return rows


def centers_fixture():
    z = pd.DataFrame(
        roster_rows(1, "C", 10, "C", {"reb": 2.0, "fg_pct": 1.0}, {"reb": 12.0, "fg_pct": 0.6})
        + roster_rows(2, "C", 11, "UT", {"reb": 1.0, "fg_pct": 0.0}, {"reb": 8.0, "fg_pct": 0.5})
        + roster_rows(3, "C", 12, "BE", {"reb": 5.0}, {"reb": 20.0})  # bench: not a starter
        + roster_rows(4, "C", None, None, {"reb": 4.0}, {"reb": 15.0})  # free agent
        + roster_rows(5, "PG", 10, "G", {"ast": 2.0}, {"ast": 9.0})  # other position
    )
    pool = pd.DataFrame(
        [
            pool_row(1, "season", fgm=6.0, fga=10.0, reb=12.0, gp=70),
            pool_row(2, "season", fgm=2.0, fga=4.0, reb=8.0, gp=40),
            pool_row(3, "season", reb=20.0, gp=10),
            pool_row(4, "season", reb=15.0, gp=60),
            pool_row(5, "season", ast=9.0, gp=80),
        ]
    )
    for col in ("pts", "reb", "ast", "stl", "blk", "fg3m"):
        pool[col] = pool.get(col, 0.0)
    return z, pool.fillna(0.0)


def test_starters_are_rostered_active_players_at_that_position():
    z, _ = centers_fixture()
    assert sorted(starter_ids(z, "season", "C")) == [1, 2]  # not the bench C, not the FA


def test_position_baseline_averages_z_and_pools_percentages():
    z, pool = centers_fixture()
    base = position_baseline(z, pool, "season", "C").set_index("category")
    assert set(base["player_id"]) == {baseline_id("C")}
    assert base.loc["reb", "z"] == pytest.approx(1.5)
    assert base.loc["reb", "value"] == pytest.approx(10.0)
    assert base.loc["fg_pct", "value"] == pytest.approx(8 / 14)  # pooled, not (0.6 + 0.5) / 2
    # z 1.5 in rebounds: only the bench C (5.0), the FA (4.0) and starter 1 (2.0) beat it.
    assert base.loc["reb", "rank"] == 4


def test_season_totals_multiply_by_games_and_pool_percentages():
    _, pool = centers_fixture()
    totals = season_totals(pool, "season", [1, 2]).set_index(["player_id", "category"])
    assert totals.loc[(1, "reb"), "total"] == 12.0 * 70
    assert totals.loc[(2, "reb"), "total"] == 8.0 * 40
    assert totals.loc[(1, "fg_pct"), ["total_num", "total_den"]].tolist() == [420.0, 700.0]
    assert totals.loc[(1, "fg_pct"), "total"] == pytest.approx(0.6)
    assert totals.loc[(1, "reb"), "gp"] == 70
    # 840 rebounds: behind only the free agent's 15 a game over 60 games (900); the
    # bench C's 20 a game is only 200 over 10 games.
    assert totals.loc[(1, "reb"), "total_rank"] == 2


def test_baseline_totals_are_its_members_averages():
    z, pool = centers_fixture()
    bid = baseline_id("C")
    totals = season_totals(pool, "season", [bid], {bid: starter_ids(z, "season", "C")})
    row = totals.set_index("category").loc["reb"]
    assert row["total"] == pytest.approx((840 + 320) / 2)
    assert row["gp"] == pytest.approx(55)


def test_totals_verdict_rewards_games_played():
    # Per game the bench C (20 rpg) out-rebounds starter 1 (12 rpg); over a season,
    # starter 1's 70 games (840) beat the bench C's 10 (200).
    z, pool = centers_fixture()
    frame = player_compare_frame(z, pool, [1, 3], "season").merge(
        season_totals(pool, "season", [1, 3]), on=["player_id", "category"]
    )
    names = {1: "Starter", 3: "Bench"}
    # Per game: Starter takes FG%, Bench takes REB. Season totals: Starter takes both.
    assert head_to_head_verdict(frame, names) == "Starter and Bench are even: 1 category each."
    assert head_to_head_verdict(frame, names, by="total_score") == "Starter wins 2 of 9 categories."
