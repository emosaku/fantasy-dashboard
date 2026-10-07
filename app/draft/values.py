"""Draft values for a points league, from ESPN's projections and the NBA schedule.

* FP/G: ESPN's projected fantasy points per game under the league's scoring (or our
  stat x points from his projected line when ESPN sends none).
* Games: ESPN's projected games, capped by his own last 3 seasons (pool.py's risk
  setting), and spread over the season by his NBA team's schedule: games a week =
  his team's games a week x the share of its games he's expected to play.
* Season points above replacement (the Value column): (FP/G - replacement) x games.
  Replacement is what's left once every roster is full: the median FP/G of the 10
  players just past the last pick, by projected season points.
"""

import pandas as pd

from draft.formats import PointsFormat
from draft.pool import FULL_SEASON, Pool, projected_games
from points import model

REPLACEMENT_POOL = 10
TYPICAL_GAMES_WEEK = 3.5
TYPICAL_DAYS_WEEK = 6.5


def points_format(pool: Pool, schedule: pd.DataFrame, starting: int, teams: int, rounds: int,
                  last_week: int, risk: str = "neutral") -> PointsFormat:  # fmt: skip
    """Fills pool.frame's games, games_week, season_points and value columns and
    returns the format the engine scores with."""
    f = pool.frame
    f["fpg"] = f["proj_fpg"].astype(float)
    games = projected_games(f["proj_games"], f["history_games"], f["injury_status"] == "OUT",
                            risk)  # fmt: skip
    weeks = list(range(1, last_week + 1))
    if schedule is not None and not schedule.empty:
        per_week = model.week_games(schedule, weeks).mean(axis=1)
        season = schedule.groupby("pro_team")["scoring_period"].nunique()
        days = float(model.week_days(schedule, weeks).mean())
    else:
        per_week, season, days = pd.Series(dtype=float), pd.Series(dtype=float), TYPICAL_DAYS_WEEK
    team_week = f["pro_team"].map(per_week).fillna(TYPICAL_GAMES_WEEK)
    team_season = f["pro_team"].map(season).fillna(FULL_SEASON)
    f["games"] = games
    f["games_week"] = team_week * (games / team_season).clip(0, 1)
    f["season_points"] = f["fpg"].fillna(0) * games
    ranked = f["season_points"].sort_values(ascending=False)
    past = ranked.iloc[teams * rounds : teams * rounds + REPLACEMENT_POOL].index
    replacement = float(f.loc[past, "fpg"].median()) if len(past) else 0.0
    f["value"] = (f["fpg"].fillna(0) - replacement) * games
    f.attrs["replacement"] = replacement
    return PointsFormat(f["fpg"].fillna(0).to_numpy(), f["games_week"].to_numpy(),
                        days, starting, f["value"].to_numpy())  # fmt: skip


def games_note(frame: pd.DataFrame, i: int) -> str:
    """ "72 games (ESPN 75, last 3 seasons 68)" for a player's card."""
    row = frame.iloc[i]
    parts = []
    if pd.notna(row.get("proj_games")):
        parts.append(f"ESPN {row['proj_games']:.0f}")
    if pd.notna(row.get("history_games")):
        parts.append(f"last 3 seasons {row['history_games']:.0f}")
    return f"{row['games']:.0f} games" + (f" ({', '.join(parts)})" if parts else "")
