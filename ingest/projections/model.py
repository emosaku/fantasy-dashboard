"""The preseason projection model: a simple, explainable system in the style of
baseball's Marcel (docs/whopDocs/projections.md).

For a target season, from each player's last three season lines (season_lines in
games.py):

1. Aging: each past season is first moved to the player's age in the target season,
   stat by stat, along an aging curve fit from the history itself (fit_aging: how each
   age's rates changed the next season). Skipped for players without a birth date.
2. Per-minute rates for every stat, the seasons weighted 5/4/3 toward the most recent
   (scaled so last season counts 1.0). Makes and attempts are projected separately, so
   FG%, FT% and 3PT% follow from them.
3. Regression to the mean: every player's history gets some minutes of league-average
   play added, so a short history lands near the league rate and a long one barely
   moves. How many minutes is fit per stat (fit_regression): few for stable stats like
   shot attempts, more for noisy ones like steals and blocks.
4. Minutes per game and games, each from the weighted history and regressed toward a
   typical rotation player. Minutes weigh last season more heavily (6/3/1): a role
   carries over more than per-minute production does.
5. The line: rate x minutes per game, plus projected games.

Players with no history (rookies) aren't projected. Seasons are named by the year they
end, as ESPN does: 2027 is 2026-27.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ingest.projections.games import STATS

RATE_STATS = [s for s in STATS if s != "MIN"]  # per-minute stats; MIN is per game


@dataclass(frozen=True)
class Params:
    # Relative weights of last season, the one before and the one before that. They're
    # scaled so last season counts 1.0, which makes every prior below read in
    # last-season terms: 1,000 minutes of league average = 1,000 minutes he played last
    # season.
    weights: tuple = (5.0, 4.0, 3.0)
    # Minutes per game follow a player's role, which carries over more strongly than
    # his per-minute production, so they lean harder on last season.
    minutes_weights: tuple = (6.0, 3.0, 1.0)
    # League-average minutes added to every history: None fits them per stat
    # (fit_regression) and scales them by regression_scale; a number uses it for all.
    regression_minutes: float | None = None
    regression_scale: float = 1.0
    regression_bounds: tuple = (50.0, 20000.0)
    mpg_prior: float = 18.0  # a typical rotation player's minutes per game
    mpg_prior_games: float = 10.0  # how many games of mpg_prior the history gets
    games_prior: float = 60.0  # a typical season's games played
    games_prior_weight: float = 0.6  # in seasons (a full last season is 1.0)
    season_games: int = 82
    min_minutes: float = 500.0  # seasons with fewer don't fit aging or regression
    aging_shrink_pairs: float = 30.0  # pulls thin ages' aging toward no change
    age_range: tuple = (19, 38)


DEFAULT = Params()


def _scaled(weights: tuple, target: int) -> dict:
    """{season: weight}, scaled so last season counts 1.0."""
    return {target - 1 - i: w / weights[0] for i, w in enumerate(weights)}


def _history(seasons: pd.DataFrame, target: int, params: Params) -> pd.DataFrame:
    """The player-season rows in the weighted window, each with its rate weight (w) and
    its minutes weight (w_min)."""
    weights = _scaled(params.weights, target)
    rows = seasons.loc[seasons["season"].isin(weights)].copy()
    rows["w"] = rows["season"].map(weights)
    rows["w_min"] = rows["season"].map(_scaled(params.minutes_weights, target))
    return rows


def league_rates(seasons: pd.DataFrame, season: int) -> pd.Series:
    """League-wide per-minute rate of every stat in one season."""
    rows = seasons.loc[seasons["season"] == season]
    return rows[RATE_STATS].sum() / rows["MIN"].sum()


def age_on(birth_dates: pd.Series, seasons) -> pd.Series:
    """Each player's age on February 1 of the season's end year (mid-season); `seasons`
    is one season or a Series of them, aligned with birth_dates."""
    born = pd.to_datetime(birth_dates)
    if np.isscalar(seasons):
        mid = pd.Timestamp(year=int(seasons), month=2, day=1)
    else:
        mid = pd.to_datetime(pd.Series(seasons, index=born.index).astype(str) + "-02-01")
    return (mid - born).dt.days / 365.25


def _birth_dates(players: pd.DataFrame | None) -> pd.Series | None:
    if players is None or "birth_date" not in players or players["birth_date"].isna().all():
        return None
    return players.set_index("player_id")["birth_date"].dropna()


def fit_aging(seasons: pd.DataFrame, players: pd.DataFrame | None, params: Params = DEFAULT):
    """How each stat's per-minute rate changes from one age to the next: a DataFrame
    indexed by age (the age moved *into*) with one log-change column per stat, or None
    without birth dates. The delta method: every pair of a player's consecutive seasons,
    both with enough minutes, weighted by the smaller minute count; ages with few pairs
    are pulled toward no change."""
    born = _birth_dates(players)
    if born is None:
        return None
    rows = seasons.loc[
        seasons["player_id"].isin(born.index) & (seasons["MIN"] >= params.min_minutes)
    ]
    nxt = rows.assign(season=rows["season"] - 1)
    pairs = rows.merge(nxt, on=["player_id", "season"], suffixes=("", "_next"))
    if pairs.empty:
        return None
    lo, hi = params.age_range
    ages = age_on(pairs["player_id"].map(born), pairs["season"] + 1)
    ages = np.clip(np.floor(ages.to_numpy()), lo, hi)
    weight = np.minimum(pairs["MIN"], pairs["MIN_next"]).to_numpy()
    out = {}
    for stat in RATE_STATS:
        before = (pairs[stat] / pairs["MIN"]).to_numpy()
        after = (pairs[f"{stat}_next"] / pairs["MIN_next"]).to_numpy()
        ok = (before > 0) & (after > 0)
        frame = pd.DataFrame({"age": ages[ok], "w": weight[ok]})
        frame["wc"] = frame["w"] * np.log(after[ok] / before[ok])
        sums = frame.groupby("age")[["w", "wc"]].sum()
        typical = frame["w"].mean() if len(frame) else 1.0
        # weighted mean change, shrunk toward 0 by aging_shrink_pairs typical pairs
        out[stat] = sums["wc"] / (sums["w"] + params.aging_shrink_pairs * typical)
    curve = pd.DataFrame(out).reindex(range(lo, hi + 1)).fillna(0.0)
    curve.index.name = "age"
    return curve


def fit_regression(seasons: pd.DataFrame, target: int, params: Params = DEFAULT) -> pd.Series:
    """Minutes of league average to add to every history, per stat: empirical Bayes on
    the three seasons before the target. Among players with enough minutes, how much
    their rates spread out (variance) is real differences plus chance; chance alone, for
    counts, is about rate / minutes. The real part sets the regression: rate / real
    variance minutes, so a stat where players truly differ a lot barely regresses."""
    rows = seasons.loc[
        seasons["season"].between(target - 3, target - 1) & (seasons["MIN"] >= params.min_minutes)
    ]
    lo, hi = params.regression_bounds
    out = {}
    for stat in RATE_STATS:
        rate = rows[stat] / rows["MIN"]
        mean = rate.mean()
        real = rate.var() - (rate / rows["MIN"]).mean()
        out[stat] = hi if not real > 0 else float(np.clip(mean / real, lo, hi))
    return pd.Series(out)


def project(
    seasons: pd.DataFrame,
    target: int,
    players: pd.DataFrame | None = None,
    params: Params = DEFAULT,
    aging: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """One row per player with any history: projected games (GP), minutes per game
    (MIN), every other stat per game, his age (if known), and history_minutes (how much
    the projection rests on; low means mostly league average)."""
    hist = _history(seasons, target, params)
    hist[RATE_STATS + ["MIN", "GP"]] = hist[RATE_STATS + ["MIN", "GP"]].astype(float)
    if hist.empty:
        return pd.DataFrame(columns=["player_id", "season", "GP", *STATS, "history_minutes"])
    league = league_rates(seasons, target - 1)
    if league.isna().any():  # no league data last season: use the whole window
        league = hist[RATE_STATS].sum() / hist["MIN"].sum()

    born = _birth_dates(players)
    ages = pd.Series(np.nan, index=pd.Index(hist["player_id"].unique(), name="player_id"))
    if born is not None:
        ages = age_on(born.reindex(ages.index), target)
    if aging is not None and born is not None:
        # move every past season to his target age along the cumulative curve
        lo, hi = params.age_range
        cumulative = aging.cumsum()
        row_born = hist["player_id"].map(born)
        known = row_born.notna()
        then = np.clip(np.floor(age_on(row_born[known], hist.loc[known, "season"])), lo, hi)
        now = np.clip(np.floor(age_on(row_born[known], target)), lo, hi)
        moved = (
            cumulative.loc[now.astype(int)].to_numpy() - cumulative.loc[then.astype(int)].to_numpy()
        )
        hist.loc[known, RATE_STATS] = hist.loc[known, RATE_STATS] * np.exp(moved)

    w = hist["w"]
    weighted = hist[RATE_STATS + ["MIN", "GP"]].mul(w, axis=0)
    weighted["w"] = w
    weighted["MIN_m"] = hist["MIN"] * hist["w_min"]
    weighted["GP_m"] = hist["GP"] * hist["w_min"]
    weighted["player_id"] = hist["player_id"]
    sums = weighted.groupby("player_id").sum()

    if params.regression_minutes is None:
        reg = fit_regression(seasons, target, params) * params.regression_scale
    else:
        reg = pd.Series(params.regression_minutes, index=RATE_STATS)
    rates = sums[RATE_STATS].add(league * reg, axis=1)
    rates = rates / np.add.outer(sums["MIN"].to_numpy(), reg.to_numpy())

    mpg = (sums["MIN_m"] + params.mpg_prior * params.mpg_prior_games) / (
        sums["GP_m"] + params.mpg_prior_games
    )
    games = (sums["GP"] + params.games_prior * params.games_prior_weight) / (
        sums["w"] + params.games_prior_weight
    )
    games = games.clip(upper=params.season_games)

    line = rates.mul(mpg, axis=0)
    line["MIN"] = mpg
    line.insert(0, "GP", games)
    line["age"] = ages.reindex(line.index)
    line["history_minutes"] = hist.groupby("player_id")["MIN"].sum()
    line.insert(0, "season", target)
    return line.reset_index()


def fantasy_points(line: pd.DataFrame, scoring: dict) -> pd.Series:
    """Per-game fantasy points of each row's line under {stat: points}."""
    total = pd.Series(0.0, index=line.index)
    for stat, points in scoring.items():
        if stat in line:
            total = total + line[stat].fillna(0) * points
    return total
