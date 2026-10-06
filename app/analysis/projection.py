"""Injury-aware projection of each team's all-play record to the end of the regular
season (Power Rankings page, "Projected finish").

Finished weeks (matchup periods before the current one) keep what actually
happened: the team's real all-play record from v_all_play. Every remaining week,
the current one included, is projected on its own from today's rosters:

  * each player contributes his per-game line -- season averages once he has them,
    ESPN's projection until then -- but only in weeks he's expected to be available;
  * a team's line is its available players' stats summed, ratio categories
    recomputed from the two totals; teams are then compared all-play on the league's
    own categories (lower-is-better ones flipped). A Most Categories league scores a
    week as one W/L/T per opponent, on category count; an Each Category league as a
    W/L/T per category, so its records count categories.

When an injured player is expected back (InjuryRules, adjustable on the page):
  1. ESPN's expected return date, when it has one: the current week plus the whole
     weeks until that date (weeks are 7 days; the All-Star week runs longer, so this
     can be a week early around it);
  2. otherwise by status -- in the IR slot: misses 4 weeks; OUT: 2; day-to-day: 1
     (the current week).
A week is missed in full and the player counts in full from his return week on.

Everyone available plays the same number of games in a projected week, so that
number never matters: scaling every team's counting stats by the same factor can't
change who beats whom. Limits: it sums every available rostered player rather than
a real starting lineup, so it doesn't model a manager moving a bench player into an
injured starter's spot.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from categories import Category, stats_needed
from trade import wide_lines


@dataclass(frozen=True)
class InjuryRules:
    day_to_day_weeks: int = 1
    out_weeks: int = 2
    ir_weeks: int = 4


def per_game_lines(pool: pd.DataFrame) -> pd.DataFrame:
    """One per-game line per rostered player from v_player_pool (long): season
    averages if he has them, else ESPN's projection. Wide: a column per stat."""
    rostered = pool.loc[pool["team_id"].notna() & pool["stat_window"].isin(["season", "projected"])]
    has_season = set(rostered.loc[rostered["stat_window"] == "season", "player_id"])
    chosen = rostered.loc[
        (rostered["stat_window"] == "season") | ~rostered["player_id"].isin(has_season)
    ]
    return wide_lines(chosen)


def back_in_week(player, current_week: int, as_of, rules: InjuryRules) -> tuple[int, str]:
    """(first week the player counts in, why). `player` needs expected_return_date,
    lineup_slot and injury_status."""
    returns = player["expected_return_date"]
    if returns is not None and not pd.isna(returns):
        days = (pd.Timestamp(returns) - pd.Timestamp(as_of)).days
        return current_week + max(days, 0) // 7, "ESPN return date"
    if player["lineup_slot"] == "IR":
        return current_week + rules.ir_weeks, "IR, no return date"
    if player["injury_status"] == "OUT":
        return current_week + rules.out_weeks, "Out"
    if player["injury_status"] == "DAY_TO_DAY":
        return current_week + rules.day_to_day_weeks, "Day-to-day"
    return current_week, "Healthy"


def availability(lines, current_week, as_of, rules) -> pd.DataFrame:
    back = [back_in_week(p, current_week, as_of, rules) for _, p in lines.iterrows()]
    return lines.assign(
        back_in_week=[b for b, _ in back],
        reason=[r for _, r in back],
    )


def team_scores(sums: np.ndarray, stat_cols: list[str], cats: list[Category]) -> np.ndarray:
    """Summed stats (teams x stat_cols) -> category scores (teams x categories):
    ratios from the two totals (NaN with nothing below the line), lower-is-better
    categories negated so higher always wins."""
    col = {c: i for i, c in enumerate(stat_cols)}
    out = np.empty((len(sums), len(cats)))
    with np.errstate(invalid="ignore", divide="ignore"):
        for k, cat in enumerate(cats):
            num = sums[:, col[cat.num]]
            if cat.kind == "ratio":
                den = sums[:, col[cat.den]]
                num = np.where(den > 0, num / den, np.nan)
            out[:, k] = -num if cat.lower_is_better else num
    return out


def week_records(scores: np.ndarray, each_category: bool = False) -> np.ndarray:
    """All-play W/L/T for one week (teams x 3). A NaN category is a tie.

    Most Categories: one result per opponent, on category count. Each Category: one
    result per opponent per category."""
    a, b = scores[:, None, :], scores[None, :, :]
    won_cat, lost_cat = a > b, a < b  # teams x teams x categories
    n, k = scores.shape
    if each_category:
        wins = won_cat.sum((1, 2))
        losses = lost_cat.sum((1, 2))
        return np.column_stack([wins, losses, (n - 1) * k - wins - losses])
    won, lost = won_cat.sum(-1), lost_cat.sum(-1)
    np.fill_diagonal(won, 0)
    np.fill_diagonal(lost, 0)
    wins = (won > lost).sum(1)
    losses = (won < lost).sum(1)
    return np.column_stack([wins, losses, (n - 1) - wins - losses])


def project_season(
    lines: pd.DataFrame,
    all_play: pd.DataFrame,
    cats: list[Category],
    current_week: int,
    last_week: int,
    as_of,
    rules: InjuryRules = InjuryRules(),
    team_ids=None,
    each_category: bool = False,
) -> pd.DataFrame:
    """One row per team: actual record so far, projected record for the remaining
    weeks (and its best/worst week), the final record, win % and rank. Records are
    matchups (Most Categories) or categories (Each Category)."""
    team_ids = list(team_ids if team_ids is not None else sorted(lines["team_id"].unique()))
    pos = {t: i for i, t in enumerate(team_ids)}
    avail = availability(lines, current_week, as_of, rules)

    stat_cols = stats_needed(cats)
    stats = avail.reindex(columns=stat_cols).fillna(0).to_numpy(float)
    owner = np.zeros((len(team_ids), len(avail)))
    owner[avail["team_id"].map(pos).to_numpy(int), np.arange(len(avail))] = 1.0
    back = avail["back_in_week"].to_numpy()

    weeks = list(range(current_week, last_week + 1))
    per_week = np.zeros((len(weeks), len(team_ids), 3))
    for k, week in enumerate(weeks):
        sums = owner @ (stats * (back <= week)[:, None])
        per_week[k] = week_records(team_scores(sums, stat_cols, cats), each_category)

    finished = all_play.loc[
        (all_play["matchup_period"] < current_week) & (all_play["matchup_period"] <= last_week)
    ]
    record_cols = (
        ["ap_cat_wins", "ap_cat_losses", "ap_cat_ties"]
        if each_category
        else ["ap_wins", "ap_losses", "ap_ties"]
    )
    actual = (
        finished.groupby("team_id")[record_cols].sum().reindex(team_ids, fill_value=0).to_numpy()
    )
    played = finished.groupby("team_id").size().reindex(team_ids, fill_value=0).to_numpy()

    projected = per_week.sum(0) if weeks else np.zeros((len(team_ids), 3))
    final = actual + projected
    games = final.sum(1)
    out = pd.DataFrame(
        {
            "team_id": team_ids,
            "weeks_played": played,
            "weeks_left": len(weeks),
            "actual_wins": actual[:, 0],
            "actual_losses": actual[:, 1],
            "actual_ties": actual[:, 2],
            "proj_wins": projected[:, 0],
            "proj_losses": projected[:, 1],
            "proj_ties": projected[:, 2],
            "week_min_wins": per_week[:, :, 0].min(0) if weeks else 0,
            "week_max_wins": per_week[:, :, 0].max(0) if weeks else 0,
            "final_wins": final[:, 0],
            "final_losses": final[:, 1],
            "final_ties": final[:, 2],
            "final_win_pct": np.where(games > 0, (final[:, 0] + 0.5 * final[:, 2]) / games, np.nan),
            "missing_now": [
                int(((avail["team_id"] == t) & (avail["back_in_week"] > current_week)).sum())
                for t in team_ids
            ],
        }
    )
    out["projected_rank"] = out["final_win_pct"].rank(ascending=False, method="min").astype("Int64")
    return out
