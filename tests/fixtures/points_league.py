"""A synthetic 4-team points league for the points engine tests.

Lineup: G, G, F, F, UT (5 starters) plus 2 bench spots: 7 players a team. Three
matchup weeks of 7 days on a fixed NBA schedule of four teams:
  AAA plays days 1, 3, 5 of each week (3 games), BBB 2, 4, 6, 7 (4), CCC 1, 2, 4, 6
  (4) and DDD 3, 5, 7 (3).
Known in advance:
  * Team 1's players are all solid (28-33 FP/G).
  * Team 3 has two players OUT with no return date, so back in week 3 by the injury
    rules: they're the first it drops when a deal leaves it a player too many.
  * Player 44 (team 4) is on IR; free agent 102 is OUT; 101 and 103 are healthy.
"""

import datetime as dt

import numpy as np
import pandas as pd

OPENING = dt.date(2026, 10, 19)  # a Monday: day 1 of week 1
SLOTS = {"G": 2, "F": 2, "UT": 1}
BENCH = 2
DAYS = {"AAA": [1, 3, 5], "BBB": [2, 4, 6, 7], "CCC": [1, 2, 4, 6], "DDD": [3, 5, 7]}
TEAMS = ["AAA", "BBB", "CCC", "DDD"]


def schedule(weeks=(1, 2, 3)) -> pd.DataFrame:
    rows = []
    for week in weeks:
        for team, days in DAYS.items():
            for day in days:
                sp = (week - 1) * 7 + day
                rows.append(
                    {
                        "pro_team": team,
                        "scoring_period": sp,
                        "game_date": OPENING + dt.timedelta(days=sp - 1),
                        "matchup_period": week,
                    }
                )
    return pd.DataFrame(rows)


def _player(pid, team, fpg, slots, pro, status="ACTIVE", ir=False):
    return {
        "player_id": pid,
        "player_name": f"P{pid}",
        "team_id": team,
        "is_free_agent": team is None or (isinstance(team, float) and np.isnan(team)),
        "is_ir": ir,
        "lineup_slot": "IR" if ir else "BE",
        "injury_status": status,
        "expected_return_date": None,
        "pro_team": pro,
        "eligible_slots": slots,
        "position": slots.split(",")[0],
        "fpg": fpg,
    }


def build_players() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    rows = []
    g, f, gf = "G,UT", "F,UT", "G,F,UT"
    shapes = [g, g, f, f, gf, g, f]
    for team in (1, 2, 3, 4):
        for k in range(7):
            pid = team * 10 + k
            fpg = float(np.round(rng.uniform(18, 34), 1))
            status, ir = "ACTIVE", False
            if team == 1:
                fpg = float(np.round(rng.uniform(28, 33), 1))  # deep
            if team == 3 and k in (5, 6):
                status = "OUT"
            if pid == 44:
                ir = True
            rows.append(_player(pid, team, fpg, shapes[k], TEAMS[(pid + k) % 4], status, ir))
    rows.append(_player(101, np.nan, 24.0, gf, "BBB"))
    rows.append(_player(102, np.nan, 40.0, g, "CCC", status="OUT"))
    rows.append(_player(103, np.nan, 21.5, f, "AAA"))
    players = pd.DataFrame(rows).set_index("player_id")
    players["team_id"] = players["team_id"].astype("float64")
    return players


def results(weeks=(), scores=None) -> pd.DataFrame:
    """Played matchups in model.played_results' shape (empty by default)."""
    cols = ["matchup_period", "team_id", "opponent_id", "points", "opponent_points",
            "is_playoff", "result"]  # fmt: skip
    if not weeks:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(scores, columns=cols)
