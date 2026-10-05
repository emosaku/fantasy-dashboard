"""The injury-aware season projection (app/analysis/projection.py)."""

import datetime as dt

import pandas as pd
import pytest

from analysis.projection import InjuryRules, back_in_week, project_season

TODAY = dt.date(2026, 11, 2)


def player(pid, team, strength, status="ACTIVE", slot="BE", returns=None):
    """Every stat scales with `strength`, so a stronger team wins every category."""
    return {
        "player_id": pid,
        "team_id": team,
        "injury_status": status,
        "lineup_slot": slot,
        "expected_return_date": returns,
        "pts": 20 * strength,
        "reb": 5 * strength,
        "ast": 4 * strength,
        "stl": strength,
        "blk": strength,
        "fg3m": 2 * strength,
        "fg3a": 5.0,
        "fgm": 4 + strength,
        "fga": 10.0,
        "ftm": 2 + strength,
        "fta": 5.0,
    }


def league(*extra):
    """Three teams of two players: team 1 strongest, team 3 weakest."""
    rows = [
        player(11, 1, 3.0), player(12, 1, 3.0),
        player(21, 2, 2.0), player(22, 2, 2.0),
        player(31, 3, 1.0), player(32, 3, 1.0),
    ]  # fmt: skip
    return pd.DataFrame(rows + list(extra))


NO_RESULTS = pd.DataFrame(columns=["team_id", "matchup_period", "ap_wins", "ap_losses", "ap_ties"])


def by_team(result):
    return result.set_index("team_id")


def test_healthy_league_projects_the_same_record_every_week():
    out = by_team(project_season(league(), NO_RESULTS, 1, 4, TODAY))
    assert out.loc[1, "proj_wins"] == 8  # beats both others in each of 4 weeks
    assert out.loc[3, "proj_losses"] == 8
    assert out.loc[2, "week_min_wins"] == out.loc[2, "week_max_wins"] == 1
    assert list(out.sort_index()["projected_rank"]) == [1, 2, 3]


def test_out_player_misses_the_default_two_weeks_then_returns():
    # Team 1's star (strength 3) is OUT; without him team 1 is a single 3.0 player,
    # weaker than team 2's two 2.0 players, so it loses that matchup while he's out.
    lines = league().assign(
        injury_status=lambda d: d["player_id"].map({11: "OUT"}).fillna("ACTIVE")
    )
    out = by_team(project_season(lines, NO_RESULTS, 1, 4, TODAY))
    assert out.loc[1, "week_min_wins"] == 1  # weeks 1-2: beats only team 3
    assert out.loc[1, "week_max_wins"] == 2  # weeks 3-4: back to beating both
    assert out.loc[1, "proj_wins"] == 1 + 1 + 2 + 2
    assert out.loc[1, "missing_now"] == 1


def test_rules_are_adjustable():
    lines = league().assign(
        injury_status=lambda d: d["player_id"].map({11: "OUT"}).fillna("ACTIVE")
    )
    out = by_team(project_season(lines, NO_RESULTS, 1, 4, TODAY, InjuryRules(out_weeks=4)))
    assert out.loc[1, "proj_wins"] == 4  # out all 4 projected weeks


def test_ir_slot_defaults_to_four_weeks_and_espn_date_wins():
    rules = InjuryRules()
    ir = {"lineup_slot": "IR", "injury_status": "OUT", "expected_return_date": None}
    assert back_in_week(ir, 5, TODAY, rules) == (9, "IR, no return date")
    dated = ir | {"expected_return_date": TODAY + dt.timedelta(days=15)}
    assert back_in_week(dated, 5, TODAY, rules) == (7, "ESPN return date")  # 2 whole weeks
    past = ir | {"expected_return_date": TODAY - dt.timedelta(days=3)}
    assert back_in_week(past, 5, TODAY, rules)[0] == 5  # already due back


def test_day_to_day_misses_only_the_current_week():
    dtd = {"lineup_slot": "G", "injury_status": "DAY_TO_DAY", "expected_return_date": None}
    healthy = dtd | {"injury_status": "ACTIVE"}
    assert back_in_week(dtd, 3, TODAY, InjuryRules())[0] == 4
    assert back_in_week(healthy, 3, TODAY, InjuryRules())[0] == 3


def test_finished_weeks_use_actual_results():
    actual = pd.DataFrame(
        {
            "team_id": [1, 2, 3, 1],
            "matchup_period": [1, 1, 1, 2],  # week 2 is the current week: not finished
            "ap_wins": [0, 2, 1, 9],
            "ap_losses": [2, 0, 1, 9],
            "ap_ties": [0, 0, 0, 0],
        }
    )
    out = by_team(project_season(league(), actual, 2, 3, TODAY))
    assert out.loc[1, "weeks_played"] == 1
    assert (out.loc[1, "actual_wins"], out.loc[1, "actual_losses"]) == (0, 2)
    assert out.loc[1, "final_wins"] == 0 + 2 * 2  # weeks 2-3 projected: beats both
    assert out.loc[2, "final_win_pct"] == pytest.approx((2 + 2) / 6)


def test_every_projected_week_balances():
    lines = league(player(41, 3, 1.0, status="DAY_TO_DAY"))
    out = project_season(lines, NO_RESULTS, 1, 6, TODAY)
    assert out["proj_wins"].sum() == out["proj_losses"].sum()
