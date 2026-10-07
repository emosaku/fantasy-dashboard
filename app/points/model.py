"""The points engine's player and team numbers. Pure pandas/numpy, no Streamlit.

In a head-to-head points league one number decides each week: the team that scores
more fantasy points wins. So:

  * A player's value is his **fantasy points per game (FP/G)** -- ESPN's own number
    for the league's scoring -- and his **points above replacement (PAR)**: FP/G minus
    the median FP/G of the 10 best healthy free agents in that window.
  * A team's strength is its **projected weekly points**: each day, the best legal
    lineup from the players with a game. Two ways to compute it:
      - fast (searches): positions ignored, each day the top S players with a game
        start (S = starting slots). A player plays a day with chance games/days, so
        his chance of starting is that times the chance that fewer than S better
        teammates play that day (a Poisson-binomial count, worked out exactly).
      - full (lineup.py): every day of every remaining week, the real schedule and
        each player's eligible slots.
  * **Expected wins a week**: each team's weekly points as a bell curve with the
    league's week-to-week spread; the chance of beating each other team, added up.

Injured players count from the week they're expected back (analysis.projection's
rules: ESPN's return date, else IR 4 weeks, OUT 2, day-to-day 1).
"""

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from analysis.projection import InjuryRules, back_in_week

WINDOWS = {
    "blended": "Blended",
    "projected": "Projected",
    "season": "Season",
    "last_7": "Last 7",
    "last_15": "Last 15",
    "last_30": "Last 30",
}
BLEND_GAMES = 20  # season FP/G counts fully from 20 games, like the categories blend
REPLACEMENT_POOL = 10  # replacement level: median of the 10 best healthy free agents
DEFAULT_SPREAD = 0.12  # week-to-week spread as a share of weekly points, until known
MIN_WEEKS_FOR_SPREAD = 3
UNAVAILABLE = {"OUT"}


# --- Players ----------------------------------------------------------------------------


def fp_wide(points: pd.DataFrame) -> pd.DataFrame:
    """player_points rows -> one row per player: fp_<window>, total_<window> and
    games_<window>."""
    if points.empty:
        return pd.DataFrame()

    def wide(column, prefix):
        return points.pivot_table(
            index="player_id", columns="stat_window", values=column, aggfunc="first"
        ).add_prefix(prefix)

    return wide("fp_per_game", "fp_").join(wide("fp_total", "total_")).join(wide("games", "games_"))


def blend(season: pd.Series, projected: pd.Series, season_games: pd.Series) -> pd.Series:
    """Season FP/G and ESPN's projection mixed by games played: alpha = min(GP/20, 1).
    Whichever one a player is missing, the other is used alone."""
    alpha = (season_games.fillna(0) / BLEND_GAMES).clip(upper=1.0)
    mixed = alpha * season + (1 - alpha) * projected
    return mixed.fillna(season).fillna(projected)


def fp_per_game(wide: pd.DataFrame, window: str) -> pd.Series:
    def col(name):
        return wide[name] if name in wide else pd.Series(np.nan, index=wide.index)

    if window == "blended":
        return blend(col("fp_season"), col("fp_projected"), col("games_season"))
    return col(f"fp_{window}")


def healthy(players: pd.DataFrame) -> pd.Series:
    return ~players["is_ir"].astype(bool) & ~players["injury_status"].isin(UNAVAILABLE)


def replacement_level(players: pd.DataFrame) -> float:
    """Median FP/G of the REPLACEMENT_POOL best healthy free agents (0 if none)."""
    free = players.loc[players["is_free_agent"].astype(bool) & healthy(players), "fpg"]
    best = free.sort_values(ascending=False).head(REPLACEMENT_POOL)
    return float(best.median()) if len(best) else 0.0


def slots_of(text) -> frozenset:
    if text is None or (isinstance(text, float) and math.isnan(text)):
        return frozenset()
    return frozenset(s for s in str(text).split(",") if s)


# --- The schedule ------------------------------------------------------------------------


def horizon_weeks(current_week: int, last_week: int) -> list[int]:
    """The weeks a projection covers: the rest of the regular season (the current
    week included), or just the current week once the regular season is over."""
    return list(range(current_week, last_week + 1)) or [current_week]


def week_games(schedule: pd.DataFrame, weeks: list[int]) -> pd.DataFrame:
    """Games per NBA team per matchup week (pro_team x week, 0 when idle)."""
    rows = schedule.loc[schedule["matchup_period"].isin(weeks)]
    table = rows.pivot_table(
        index="pro_team", columns="matchup_period", values="scoring_period", aggfunc="nunique"
    )
    return table.reindex(columns=weeks).fillna(0)


def week_days(schedule: pd.DataFrame, weeks: list[int]) -> pd.Series:
    """Days with at least one NBA game in each week."""
    rows = schedule.loc[schedule["matchup_period"].isin(weeks)]
    return rows.groupby("matchup_period")["scoring_period"].nunique().reindex(weeks).fillna(0)


def first_week_back(players: pd.DataFrame, current_week: int, as_of, rules=None) -> pd.Series:
    """The first week each player counts in (current_week when healthy)."""
    rules = rules or InjuryRules()
    return pd.Series(
        [back_in_week(p, current_week, as_of, rules)[0] for _, p in players.iterrows()],
        index=players.index,
        dtype="int64",
    )


def games_by_week(players: pd.DataFrame, schedule: pd.DataFrame, weeks: list[int],
                  back: pd.Series) -> pd.DataFrame:  # fmt: skip
    """player x week: his NBA team's games that week, 0 before he's back."""
    table = week_games(schedule, weeks)
    games = table.reindex(players["pro_team"].fillna("")).fillna(0).to_numpy()
    out = pd.DataFrame(games, index=players.index, columns=weeks)
    for week in weeks:
        out.loc[back > week, week] = 0
    return out


# --- Team strength -----------------------------------------------------------------------


def start_chances(play: np.ndarray, slots: int) -> np.ndarray:
    """For players already sorted best first, on rows of any leading shape: the
    chance each one starts on a day he plays, i.e. that fewer than `slots` better
    teammates play that day. `play` is each player's chance of playing a given day."""
    lead, n = play.shape[:-1], play.shape[-1]
    counts = np.zeros((*lead, slots + 1))  # P(k better players playing), k capped at slots
    counts[..., 0] = 1.0
    out = np.empty(play.shape)
    for r in range(n):
        q = play[..., r : r + 1]
        out[..., r] = counts[..., :slots].sum(axis=-1)
        moved = counts * q
        counts = counts * (1 - q)
        counts[..., 1:] += moved[..., :-1]
        counts[..., slots] += moved[..., slots]
    return out


def fast_weekly_points(fpg: np.ndarray, games: np.ndarray, days: float, slots: int) -> np.ndarray:
    """Projected weekly points, positions ignored, for rosters on the last axis
    (padding: fpg 0 and games 0). Rows are sorted best first here."""
    fpg, games = np.asarray(fpg, float), np.asarray(games, float)
    if days <= 0:
        return np.zeros(fpg.shape[:-1])
    order = np.argsort(-np.where(games > 0, fpg, -np.inf), axis=-1, kind="stable")
    fpg = np.take_along_axis(fpg, order, axis=-1)
    games = np.take_along_axis(games, order, axis=-1)
    play = np.clip(games / days, 0, 1)
    starts = start_chances(play, slots)
    return (np.where(games > 0, fpg, 0) * games * starts).sum(axis=-1)


# --- Expected wins -----------------------------------------------------------------------


def phi(x):
    """Standard normal CDF, elementwise (erf by Abramowitz-Stegun 7.1.26, error under
    1.5e-7: far below anything shown)."""
    z = np.asarray(x, float) / math.sqrt(2)
    t = 1.0 / (1.0 + 0.3275911 * np.abs(z))
    poly = t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027
           + t * 1.061405429))))  # fmt: skip
    erf = np.sign(z) * (1.0 - poly * np.exp(-z * z))
    return 0.5 * (1.0 + erf)


def expected_wins(mu: pd.Series, sigma: float) -> pd.Series:
    """E_i = sum over j != i of P(team i outscores team j in a week):
    Phi((mu_i - mu_j) / sqrt(sigma_i^2 + sigma_j^2)), one league-wide sigma."""
    values = mu.to_numpy(float)
    scale = math.sqrt(2) * max(sigma, 1e-9)
    p = phi((values[:, None] - values[None, :]) / scale)
    np.fill_diagonal(p, 0.0)
    return pd.Series(p.sum(axis=1), index=mu.index)


def weekly_spread(results: pd.DataFrame, mu: pd.Series) -> tuple[float, str]:
    """(sigma, how it was found): the spread of teams' weekly scores around their own
    average over the played regular-season weeks, once there are MIN_WEEKS_FOR_SPREAD
    of them; before that, DEFAULT_SPREAD of the average projected weekly score."""
    played = results.loc[~results["is_playoff"]] if not results.empty else results
    if not played.empty and played["matchup_period"].nunique() >= MIN_WEEKS_FOR_SPREAD:
        residual = played["points"] - played.groupby("team_id")["points"].transform("mean")
        weeks = played["matchup_period"].nunique()
        dof = max(len(played) - played["team_id"].nunique(), 1)
        sigma = float(np.sqrt((residual**2).sum() / dof))
        if sigma > 0:
            return sigma, f"from {weeks} weeks played"
    return DEFAULT_SPREAD * float(mu.mean() or 0), "an early-season estimate (12% of a week)"


# --- Results: standings, all-play, luck --------------------------------------------------


def played_results(scores: pd.DataFrame, current_week: int) -> pd.DataFrame:
    """Finished matchups (weeks before the current one) with each side's result."""
    done = scores.loc[scores["matchup_period"] < current_week].copy()
    done["result"] = np.select(
        [done["points"] > done["opponent_points"], done["points"] < done["opponent_points"]],
        ["W", "L"],
        "T",
    )
    return done


def all_play(results: pd.DataFrame) -> pd.DataFrame:
    """Per team per week: how many teams it outscored (W), was outscored by (L) and
    tied (T) that week, regular season and playoffs alike."""
    rows = []
    for week, group in results.groupby("matchup_period"):
        pts = group.set_index("team_id")["points"]
        for team, score in pts.items():
            others = pts.drop(team)
            rows.append(
                {
                    "matchup_period": week,
                    "team_id": team,
                    "ap_wins": int((score > others).sum()),
                    "ap_losses": int((score < others).sum()),
                    "ap_ties": int((score == others).sum()),
                }
            )
    return pd.DataFrame(rows, columns=["matchup_period", "team_id", "ap_wins", "ap_losses",
                                       "ap_ties"])  # fmt: skip


def win_pct(wins, losses, ties):
    games = wins + losses + ties
    return (wins + 0.5 * ties) / games.where(games > 0)


def season_table(results: pd.DataFrame) -> pd.DataFrame:
    """Per team, season to date: record, points for and against, all-play record and
    win %, luck (actual win % minus all-play win %)."""
    if results.empty:
        return pd.DataFrame()
    ap = all_play(results).groupby("team_id")[["ap_wins", "ap_losses", "ap_ties"]].sum()
    real = results.groupby("team_id").agg(
        wins=("result", lambda r: int((r == "W").sum())),
        losses=("result", lambda r: int((r == "L").sum())),
        ties=("result", lambda r: int((r == "T").sum())),
        points_for=("points", "sum"),
        points_against=("opponent_points", "sum"),
        weeks=("matchup_period", "nunique"),
    )
    out = real.join(ap)
    out["win_pct"] = win_pct(out["wins"], out["losses"], out["ties"])
    out["ap_win_pct"] = win_pct(out["ap_wins"], out["ap_losses"], out["ap_ties"])
    out["luck"] = out["win_pct"] - out["ap_win_pct"]
    out["points_per_week"] = out["points_for"] / out["weeks"]
    return out


def luck_by_week(results: pd.DataFrame) -> pd.DataFrame:
    """Season-to-date luck through each week, per team."""
    if results.empty:
        return pd.DataFrame()
    ap = all_play(results)
    weekly = results[["matchup_period", "team_id", "result"]].merge(
        ap, on=["matchup_period", "team_id"]
    )
    weekly["actual"] = weekly["result"].map({"W": 1.0, "L": 0.0, "T": 0.5})
    games = weekly[["ap_wins", "ap_losses", "ap_ties"]].sum(axis=1)
    weekly["ap_pct"] = (weekly["ap_wins"] + 0.5 * weekly["ap_ties"]) / games.where(games > 0)
    weekly = weekly.sort_values(["team_id", "matchup_period"])
    grouped = weekly.groupby("team_id")
    weekly["actual_to_date"] = grouped["actual"].cumsum() / (grouped.cumcount() + 1)
    weekly["ap_to_date"] = grouped["ap_pct"].cumsum() / (grouped.cumcount() + 1)
    weekly["luck"] = weekly["actual_to_date"] - weekly["ap_to_date"]
    return weekly


# --- Projected finish ---------------------------------------------------------------------


@dataclass(frozen=True)
class Finish:
    team_id: int
    wins: float
    losses: float
    ties: int


def projected_finish(scores: pd.DataFrame, mu: pd.Series, sigma: float, current_week: int,
                     last_week: int, current_share_left: float = 1.0) -> pd.DataFrame:  # fmt: skip
    """Each team's projected regular-season record: finished weeks as they happened,
    every remaining matchup won with chance Phi((mu_i - mu_j) / (sigma sqrt 2)). In the
    current week, the points already scored count, plus `current_share_left` of a
    week's projection for the days still to play."""
    regular = scores.loc[~scores["is_playoff"] & (scores["matchup_period"] <= last_week)]
    done = played_results(regular, current_week)
    out = {
        t: {"wins": 0.0, "losses": 0.0, "ties": 0}
        for t in sorted(set(regular["team_id"]) | set(mu.index))
    }
    for row in done.itertuples():
        key = {"W": "wins", "L": "losses", "T": "ties"}[row.result]
        out[row.team_id][key] += 1
    scale = math.sqrt(2) * max(sigma, 1e-9)
    ahead = regular.loc[regular["matchup_period"] >= current_week]
    for row in ahead.itertuples():
        mine, theirs = mu.get(row.team_id, 0.0), mu.get(row.opponent_id, 0.0)
        if row.matchup_period == current_week:
            mine = row.points + current_share_left * mine
            theirs = row.opponent_points + current_share_left * theirs
            spread = scale * math.sqrt(max(current_share_left, 1e-6))
        else:
            spread = scale
        p = float(phi(np.array([(mine - theirs) / spread]))[0])
        out[row.team_id]["wins"] += p
        out[row.team_id]["losses"] += 1 - p
    table = pd.DataFrame.from_dict(out, orient="index")
    table.index.name = "team_id"
    return table


# --- Points by source -------------------------------------------------------------------

SOURCES = {
    "PTS": "Scoring", "FGM": "Scoring", "FTM": "Scoring",
    "3PM": "Threes",
    "REB": "Rebounds", "OREB": "Rebounds", "DREB": "Rebounds",
    "AST": "Assists",
    "STL": "Steals and blocks", "BLK": "Steals and blocks",
}  # fmt: skip
PENALTIES = "Misses and turnovers"
OTHER = "Other"
SOURCE_ORDER = ["Scoring", "Threes", "Rebounds", "Assists", "Steals and blocks", OTHER, PENALTIES]


def source_of(stat: str, points: float) -> str:
    return PENALTIES if points < 0 else SOURCES.get(stat, OTHER)


def points_by_stat(lines: pd.DataFrame, scoring: list[dict]) -> pd.DataFrame:
    """Per-game fantasy points from each scored stat: player x stat (lines: a row per
    player, a column per per-game stat)."""
    out = {}
    for item in scoring:
        values = lines[item["stat"]] if item["stat"] in lines else 0.0
        out[item["stat"]] = pd.Series(values, index=lines.index, dtype="float64").fillna(0) * float(
            item["points"]
        )
    return pd.DataFrame(out, index=lines.index)


def points_by_source(by_stat: pd.DataFrame, scoring: list[dict],
                     espn_fpg: pd.Series | None = None) -> pd.DataFrame:  # fmt: skip
    """by_stat grouped into SOURCE_ORDER. With ESPN's FP/G, whatever ESPN counts that
    the stat line doesn't (bonuses like double-doubles) is added to Other."""
    groups = {item["stat"]: source_of(item["stat"], item["points"]) for item in scoring}
    out = by_stat.T.groupby(groups).sum().T.reindex(columns=SOURCE_ORDER, fill_value=0.0)
    if espn_fpg is not None:
        out[OTHER] += (espn_fpg.reindex(out.index) - by_stat.sum(axis=1)).fillna(0)
    return out
