"""The app's own math: category totals and formatting, Compare's season lines,
z-scores and head-to-head, and the Trade Analyzer's before/after/delta. Every
expected value is worked out by hand. Categories are data: the original league's
nine, plus turnovers (lower wins) and A/TO (a ratio that isn't a percentage)."""

import math

import pandas as pd
import pytest

from analysis.rankings import player_rankings
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
from compare import (
    baseline_id,
    head_to_head,
    head_to_head_verdict,
    period_lines,
    player_compare_frame,
    position_baseline,
    scores,
    season_totals,
    starter_ids,
    zscores,
)
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


# --- Compare: Players mode ----------------------------------------------------------


def z_rows(pid, name, team, window, zs, values=None, ratios=None, position="G", slot="BE"):
    """v_player_z-shaped rows for one player in one stat window, one per category in
    CATS: zs maps category -> z (others 0); values defaults to z; ratios maps a ratio
    category -> its (num, den) per game. Blended rows carry no num/den, like the view."""
    rows = []
    for order, cat in enumerate(CATS):
        if window == "blended":
            num = den = float("nan")
        elif cat.kind == "ratio":
            num, den = (ratios or {}).get(cat.key, (0.0, 0.0))
        else:
            num, den = (values or zs).get(cat.key, 0.0), 0.0
        rows.append(
            {
                "player_id": pid,
                "player_name": name,
                "team_id": team,
                "is_free_agent": team is None,
                "is_ir": False,
                "injury_status": "ACTIVE",
                "position": position,
                "lineup_slot": slot,
                "stat_window": window,
                "category": cat.key,
                "kind": cat.kind,
                "lower_is_better": cat.lower_is_better,
                "display_order": order,
                "z": zs.get(cat.key, 0.0),
                "value": (values or zs).get(cat.key, 0.0),
                "num": num,
                "den": den,
            }
        )
    return rows


def pool_rows(pid, window, **stats):
    """v_player_pool-shaped rows (long: one per stat) for one player and window."""
    return [
        {"player_id": pid, "stat_window": window, "stat": s, "value": v} for s, v in stats.items()
    ]


def compare_fixture():
    return pd.DataFrame(
        z_rows(1, "Star", 10, "season", {"PTS": 2.0, "FG%": 1.5}, {"PTS": 28.0, "FG%": 0.52},
               {"FG%": (13.0, 25.0)})
        + z_rows(2, "Sharpshooter", 11, "season", {"FG%": -0.5, "3PM": 2.0},
                 {"FG%": 0.60, "3PM": 3.5}, {"FG%": (3.0, 5.0)})
        + z_rows(3, "Free agent", None, "season", {"PTS": 1.0}, {"PTS": 20.0})
        + z_rows(1, "Star", 10, "projected", {"PTS": 1.0}, {"PTS": 24.0})
    )  # fmt: skip


def test_player_compare_frame_matches_player_rankings_for_the_same_window():
    z = compare_fixture()
    frame = player_compare_frame(z, [1, 2], "season", CATS)
    ranks = player_rankings(z.loc[z["stat_window"] == "season"])
    for pid in (1, 2):
        for key in keys(CATS):
            row = frame.loc[(frame["player_id"] == pid) & (frame["category"] == key)].iloc[0]
            assert row["z"] == pytest.approx(ranks.at[pid, f"{key}_z"])
            assert row["rank"] == ranks.at[pid, f"{key}_rank"]


def test_player_compare_frame_loads_both_rostered_and_free_agent():
    frame = player_compare_frame(compare_fixture(), [1, 3], "season", CATS)
    assert set(frame["player_id"]) == {1, 3}
    assert (
        frame.loc[(frame["player_id"] == 3) & (frame["category"] == "PTS"), "value"].iloc[0] == 20
    )


def test_player_compare_frame_ratio_rows_carry_their_two_totals():
    frame = player_compare_frame(compare_fixture(), [1, 2], "season", CATS)
    frame = frame.set_index(["player_id", "category"])
    assert frame.loc[(1, "FG%"), ["num", "den"]].tolist() == [13.0, 25.0]
    assert frame.loc[(2, "FG%"), ["num", "den"]].tolist() == [3.0, 5.0]
    assert math.isnan(frame.loc[(1, "PTS"), "num"])  # a count: no totals shown


def test_player_compare_frame_respects_the_chosen_window():
    frame = player_compare_frame(compare_fixture(), [1], "projected", CATS).set_index("category")
    assert frame.loc["PTS", "value"] == 24.0  # the projected row, not season's 28.0


def test_verdict_counts_by_z_so_volume_beats_raw_percentage():
    # Sharpshooter's raw FG% (60%) beats Star's (52%), but on 25 attempts to 5 Star's
    # z is higher, so FG% goes to Star.
    frame = player_compare_frame(compare_fixture(), [1, 2], "season", CATS)
    verdict = head_to_head_verdict(frame, {1: "Star", 2: "Sharpshooter"})
    assert verdict == "Star wins 2 of 11 categories; Sharpshooter is better in 3PM."


def test_verdict_gives_turnovers_to_the_player_with_fewer():
    z = pd.DataFrame(
        z_rows(1, "Careful", 10, "season", {"TO": 1.0}, {"TO": 1.0})
        + z_rows(2, "Sloppy", 11, "season", {"TO": -1.0}, {"TO": 3.5})
    )
    frame = player_compare_frame(z, [1, 2], "season", CATS)
    assert head_to_head_verdict(frame, {1: "Careful", 2: "Sloppy"}) == (
        "Careful wins 1 of 11 categories."
    )


def test_verdict_handles_a_tie():
    z = pd.DataFrame(z_rows(1, "A", 10, "season", {}) + z_rows(2, "B", 11, "season", {}))
    frame = player_compare_frame(z, [1, 2], "season", CATS)
    assert head_to_head_verdict(frame, {1: "A", 2: "B"}) == "A and B are even: 0 categories each."


def test_verdict_requires_exactly_two_players():
    frame = player_compare_frame(compare_fixture(), [1, 2, 3], "season", CATS)
    with pytest.raises(ValueError, match="exactly 2"):
        head_to_head_verdict(frame, {1: "Star", 2: "Sharpshooter", 3: "Free agent"})


def test_blended_totals_fall_back_to_season_then_projected():
    # Blended rows carry no num/den: a player with a season line uses it, one with
    # only a projected line falls back to that.
    z = pd.DataFrame(
        z_rows(1, "A", 10, "season", {}, ratios={"FG%": (10.0, 20.0)})
        + z_rows(1, "A", 10, "projected", {}, ratios={"FG%": (99.0, 99.0)})  # ignored
        + z_rows(2, "B", 11, "projected", {}, ratios={"FG%": (4.0, 8.0)})
        + z_rows(1, "A", 10, "blended", {})
        + z_rows(2, "B", 11, "blended", {})
    )
    frame = player_compare_frame(z, [1, 2], "blended", CATS).set_index(["player_id", "category"])
    assert frame.loc[(1, "FG%"), ["num", "den"]].tolist() == [10.0, 20.0]
    assert frame.loc[(2, "FG%"), ["num", "den"]].tolist() == [4.0, 8.0]


# --- Players mode: position baseline and season totals ------------------------------


def centers_fixture():
    z = pd.DataFrame(
        z_rows(1, "P1", 10, "season", {"REB": 2.0, "FG%": 1.0}, {"REB": 12.0, "FG%": 0.6},
               {"FG%": (6.0, 10.0)}, position="C", slot="C")
        + z_rows(2, "P2", 11, "season", {"REB": 1.0}, {"REB": 8.0, "FG%": 0.5},
                 {"FG%": (2.0, 4.0)}, position="C", slot="UT")
        + z_rows(3, "P3", 12, "season", {"REB": 5.0}, {"REB": 20.0}, position="C",
                 slot="BE")  # bench: not a starter
        + z_rows(4, "P4", None, "season", {"REB": 4.0}, {"REB": 15.0}, position="C",
                 slot=None)  # free agent
        + z_rows(5, "P5", 10, "season", {"AST": 2.0}, {"AST": 9.0}, position="PG", slot="G")
    )  # fmt: skip
    pool = pd.DataFrame(
        pool_rows(1, "season", FGM=6.0, FGA=10.0, REB=12.0, GP=70)
        + pool_rows(2, "season", FGM=2.0, FGA=4.0, REB=8.0, GP=40)
        + pool_rows(3, "season", REB=20.0, GP=10)
        + pool_rows(4, "season", REB=15.0, GP=60)
        + pool_rows(5, "season", AST=9.0, GP=80)
    )
    return z, pool


def test_starters_are_rostered_active_players_at_that_position():
    z, _ = centers_fixture()
    assert sorted(starter_ids(z, "season", "C")) == [1, 2]  # not the bench C, not the FA


def test_position_baseline_averages_z_and_pools_ratios():
    z, _ = centers_fixture()
    base = position_baseline(z, "season", "C", CATS).set_index("category")
    assert set(base["player_id"]) == {baseline_id("C")}
    assert base.loc["REB", "z"] == pytest.approx(1.5)
    assert base.loc["REB", "value"] == pytest.approx(10.0)
    assert base.loc["FG%", "value"] == pytest.approx(8 / 14)  # pooled, not (0.6 + 0.5) / 2
    # z 1.5 in rebounds: only the bench C (5.0), the FA (4.0) and starter 1 (2.0) beat it.
    assert base.loc["REB", "rank"] == 4


def test_season_totals_multiply_by_games_and_pool_ratios():
    _, pool = centers_fixture()
    totals = season_totals(pool, "season", [1, 2], CATS).set_index(["player_id", "category"])
    assert totals.loc[(1, "REB"), "total"] == 12.0 * 70
    assert totals.loc[(2, "REB"), "total"] == 8.0 * 40
    assert totals.loc[(1, "FG%"), ["total_num", "total_den"]].tolist() == [420.0, 700.0]
    assert totals.loc[(1, "FG%"), "total"] == pytest.approx(0.6)
    assert totals.loc[(1, "REB"), "gp"] == 70
    # 840 rebounds: behind only the free agent's 15 a game over 60 games (900); the
    # bench C's 20 a game is only 200 over 10 games.
    assert totals.loc[(1, "REB"), "total_rank"] == 2


def test_season_totals_flip_turnovers_and_pool_a_to():
    pool = pd.DataFrame(
        pool_rows(1, "season", AST=6.0, TO=2.0, GP=70)
        + pool_rows(2, "season", AST=2.0, TO=1.0, GP=10)
    )
    totals = season_totals(pool, "season", [1, 2], CATS).set_index(["player_id", "category"])
    assert totals.loc[(1, "TO"), "total"] == 140.0  # shown as the real count
    assert totals.loc[(1, "TO"), "total_score"] == -140.0  # judged with fewer = better
    assert totals.loc[(2, "TO"), "total_rank"] == 1 and totals.loc[(1, "TO"), "total_rank"] == 2
    assert totals.loc[(1, "A/TO"), "total"] == pytest.approx(420 / 140)  # pooled, 3.0
    assert totals.loc[(1, "A/TO"), "total_rank"] == 1


def test_baseline_totals_are_its_members_averages():
    z, pool = centers_fixture()
    bid = baseline_id("C")
    totals = season_totals(pool, "season", [bid], CATS, {bid: starter_ids(z, "season", "C")})
    row = totals.set_index("category").loc["REB"]
    assert row["total"] == pytest.approx((840 + 320) / 2)
    assert row["gp"] == pytest.approx(55)


def test_totals_verdict_rewards_games_played():
    # Per game the bench C (20 rpg) out-rebounds starter 1 (12 rpg); over a season,
    # starter 1's 70 games (840) beat the bench C's 10 (200).
    z, pool = centers_fixture()
    frame = player_compare_frame(z, [1, 3], "season", CATS).merge(
        season_totals(pool, "season", [1, 3], CATS), on=["player_id", "category"]
    )
    names = {1: "Starter", 3: "Bench"}
    # Per game: Starter takes FG%, Bench takes REB. Season totals: Starter takes both.
    assert head_to_head_verdict(frame, names) == "Starter and Bench are even: 1 category each."
    assert (
        head_to_head_verdict(frame, names, by="total_score") == "Starter wins 2 of 11 categories."
    )
