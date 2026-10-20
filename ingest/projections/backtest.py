"""Scores projections against real seasons (docs/whopDocs/projections.md, "How we'll
know it's good enough").

For each test season the model is fit on earlier seasons only, then compared with what
happened for players who played enough minutes. Every method is scored on the same
players: the model, "repeat last season" (the baseline it must clearly beat), and any
other projections passed in (ESPN's snapshot, for the internal benchmark).

Measures, per method and season:
* mae_<STAT>  -- mean absolute error per game, each of the 15 stats
* mae_fpg     -- fantasy points per game, ESPN's default points scoring
* mae_fp      -- season fantasy points (per game x games: what games projection adds)
* rank_corr   -- rank correlation of fantasy points per game among the top players
"""

import itertools

import pandas as pd

from ingest.projections.games import STATS
from ingest.projections.model import DEFAULT, Params, fantasy_points, fit_aging, project

# ESPN's default head-to-head points league
ESPN_POINTS = {"PTS": 1.0, "3PM": 1.0, "FGA": -1.0, "FGM": 2.0, "FTA": -1.0, "FTM": 1.0,
               "REB": 1.0, "AST": 2.0, "STL": 4.0, "BLK": 4.0, "TO": -2.0}  # fmt: skip
MIN_MINUTES = 500.0
TOP_N = 150


def per_game(lines: pd.DataFrame) -> pd.DataFrame:
    """Season totals (season_lines) -> per-game lines, GP kept as games."""
    out = lines[["player_id", "GP"]].copy()
    for stat in STATS:
        out[stat] = lines[stat] / lines["GP"]
    return out


def last_season(seasons: pd.DataFrame, target: int) -> pd.DataFrame:
    """The baseline: each player's previous season, repeated."""
    return per_game(seasons.loc[seasons["season"] == target - 1])


def score(projected: pd.DataFrame, actual: pd.DataFrame, scoring: dict, top_n: int) -> dict:
    both = actual.merge(projected, on="player_id", suffixes=("", "_p"))
    out = {f"mae_{s}": (both[f"{s}_p"] - both[s]).abs().mean() for s in STATS}
    fpg = fantasy_points(both[STATS], scoring)
    fpg_p = fantasy_points(both[[f"{s}_p" for s in STATS]].set_axis(STATS, axis=1), scoring)
    out["mae_fpg"] = (fpg_p - fpg).abs().mean()
    out["mae_fp"] = (fpg_p * both["GP_p"] - fpg * both["GP"]).abs().mean()
    top = fpg.nlargest(min(top_n, len(fpg))).index
    out["rank_corr"] = fpg[top].rank().corr(fpg_p[top].rank())  # Spearman, without scipy
    out["players"] = len(both)
    return out


def backtest(
    seasons: pd.DataFrame,
    test_seasons: list[int],
    players: pd.DataFrame | None = None,
    params: Params = DEFAULT,
    others: dict | None = None,
    scoring: dict = ESPN_POINTS,
    min_minutes: float = MIN_MINUTES,
    top_n: int = TOP_N,
) -> pd.DataFrame:
    """One row per test season x method, a column per measure.

    seasons: season_lines for every season available. others: {name: {season:
    per-game projections}} scored alongside, on the same players."""
    rows = []
    for target in test_seasons:
        known = seasons.loc[seasons["season"] < target]
        aging = fit_aging(known, players, params)
        actual = per_game(
            seasons.loc[(seasons["season"] == target) & (seasons["MIN"] >= min_minutes)]
        )
        methods = {
            "model": project(known, target, players, params, aging),
            "last_season": last_season(seasons, target),
        }
        for name, by_season in (others or {}).items():
            if target in by_season:
                methods[name] = by_season[target]
        common = set(actual["player_id"])
        for frame in methods.values():
            common &= set(frame["player_id"])
        actual = actual.loc[actual["player_id"].isin(common)]
        for name, frame in methods.items():
            frame = frame.loc[frame["player_id"].isin(common), ["player_id", "GP", *STATS]]
            rows.append({"season": target, "method": name} | score(frame, actual, scoring, top_n))
    return pd.DataFrame(rows)


def tune(
    seasons: pd.DataFrame,
    test_seasons: list[int],
    players: pd.DataFrame | None = None,
    grid: dict | None = None,
    measure: str = "mae_fpg",
) -> tuple[Params, pd.DataFrame]:
    """Tries every combination of the grid's Params values and returns the one with the
    lowest average `measure` across the test seasons, plus every result."""
    grid = grid or {
        "regression_scale": [1.0, 2.0, 3.0, 5.0],
        "minutes_weights": [(6.0, 3.0, 1.0), (10.0, 2.0, 1.0), (1.0, 0.0, 0.0)],
        "mpg_prior_games": [5.0, 10.0, 20.0],
    }
    keys = list(grid)
    results = []
    for values in itertools.product(*(grid[k] for k in keys)):
        params = Params(**dict(zip(keys, values, strict=True)))
        scored = backtest(seasons, test_seasons, players, params)
        model = scored.loc[scored["method"] == "model", measure].mean()
        results.append(dict(zip(keys, values, strict=True)) | {measure: model})
    table = pd.DataFrame(results).sort_values(measure)
    best = table.iloc[0]
    return Params(**{k: best[k] for k in keys}), table.reset_index(drop=True)
