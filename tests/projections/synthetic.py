"""A synthetic league with known "true" talent, so tests can check the model recovers
what generated the data: each player has true per-minute rates, minutes per game,
games played and an age, and every season's line is drawn with real-world-sized noise.
"""

import numpy as np
import pandas as pd
from ingest.projections.games import STATS

# League-average per-minute rates, roughly the NBA's
BASE = {"OREB": 0.045, "DREB": 0.145, "AST": 0.105, "STL": 0.032, "BLK": 0.022,
        "TO": 0.058, "3PA": 0.155, "FGA": 0.36, "FTA": 0.09}  # fmt: skip
PCT = {"FG": 0.47, "3P": 0.36, "FT": 0.78}
DRIFT = 0.06  # yearly random change in talent (log scale)
MPG_DRIFT = 3.0  # yearly random change in minutes per game


def aging_curve(age: np.ndarray) -> np.ndarray:
    """True log change of every rate when moving into `age`: +4%/year to 26, flat to
    30, then -5%/year."""
    return np.where(age <= 26, 0.04, np.where(age <= 30, 0.0, -0.05))


def league(players: int = 400, seasons=range(2019, 2027), seed: int = 7, aging: bool = True):
    """(season_lines, players): totals per player-season, and birth dates."""
    rng = np.random.default_rng(seed)
    talent = {s: BASE[s] * rng.lognormal(0, 0.35, players) for s in BASE}
    pct = {k: np.clip(rng.normal(v, 0.04, players), 0.2, 0.95) for k, v in PCT.items()}
    mpg = rng.uniform(10, 36, players)
    availability = rng.beta(6, 1.5, players)
    first, last = min(seasons), max(seasons)
    age_last = rng.uniform(20, 37, players)  # age in the last season; younger ones join later
    age0 = age_last - (last - first)
    born = pd.to_datetime([f"{last}-02-01"] * players) - pd.to_timedelta(age_last * 365.25, "D")

    rows = []
    level = np.zeros(players)  # accumulated log aging and drift
    for season in seasons:
        age = age0 + (season - first)
        if season > first:
            # talent drifts a little every year, and roles change minutes
            level = level + rng.normal(0, DRIFT, players)
            mpg = np.clip(mpg + rng.normal(0, MPG_DRIFT, players), 6, 38)
            if aging:
                level = level + aging_curve(np.floor(age))
        games = rng.binomial(82, availability) * (age >= 19.5)  # not in the league yet
        minutes = np.round(games * mpg * rng.lognormal(0, 0.05, players))
        line = {"player_id": np.arange(1, players + 1), "season": season, "GP": games,
                "MIN": minutes}  # fmt: skip
        for stat, rate in talent.items():
            line[stat] = rng.poisson(rate * np.exp(level) * minutes)
        line["REB"] = line["OREB"] + line["DREB"]
        line["FGM"] = rng.binomial(line["FGA"], pct["FG"])
        line["3PM"] = rng.binomial(line["3PA"], pct["3P"])
        line["FTM"] = rng.binomial(line["FTA"], pct["FT"])
        line["PTS"] = 2 * line["FGM"] + line["3PM"] + line["FTM"]
        rows.append(pd.DataFrame(line))
    lines = pd.concat(rows, ignore_index=True)
    lines = lines.loc[lines["GP"] > 0, ["player_id", "season", "GP", *STATS]]
    people = pd.DataFrame({"player_id": np.arange(1, players + 1), "birth_date": born})
    return lines.reset_index(drop=True), people


def season_row(player_id: int, season: int, gp: float, minutes: float, **stats) -> dict:
    """One hand-made season line; unspecified stats are 0."""
    return {"player_id": player_id, "season": season, "GP": gp, "MIN": minutes} | {
        s: float(stats.get(s, 0.0)) for s in STATS if s != "MIN"
    }
