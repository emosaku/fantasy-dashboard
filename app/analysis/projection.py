"""Injury-aware projection of each team's all-play record to the end of the regular
season (Power Rankings page, "Projected finish").

Finished weeks (matchup periods before the current one) keep what actually
happened: the team's real all-play record from v_all_play. Every remaining week,
the current one included, is projected on its own from today's rosters:

  * each player contributes his per-game line -- season averages once he has them,
    ESPN's projection until then -- but only in weeks he's expected to be available;
  * a team's line is its available players' stats summed, percentages recomputed
    from makes and attempts; teams are then compared on the 9 categories, all-play,
    and a week is a W/L/T on category count (the league is H2H Most Categories).

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

from categories import COLUMNS, PCT_PARTS

SUM_COLUMNS = ["pts", "reb", "ast", "stl", "blk", "fg3m", "fg3a", "fgm", "fga", "ftm", "fta"]


@dataclass(frozen=True)
class InjuryRules:
    day_to_day_weeks: int = 1
    out_weeks: int = 2
    ir_weeks: int = 4


def per_game_lines(pool: pd.DataFrame) -> pd.DataFrame:
    """One per-game line per rostered player from v_player_pool: season averages if he
    has them, else ESPN's projection."""
    rostered = pool.loc[pool["team_id"].notna() & pool["stat_window"].isin(["season", "projected"])]
    return (
        rostered.sort_values("stat_window", ascending=False)  # 'season' before 'projected'
        .drop_duplicates("player_id")
        .reset_index(drop=True)
    )


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


def _team_lines(sums: np.ndarray) -> np.ndarray:
    """Summed stats (teams x SUM_COLUMNS) -> the 9 categories (teams x 9)."""
    col = {c: i for i, c in enumerate(SUM_COLUMNS)}
    out = np.empty((len(sums), len(COLUMNS)))
    with np.errstate(invalid="ignore", divide="ignore"):
        for k, c in enumerate(COLUMNS):
            if c in PCT_PARTS:
                makes, attempts = PCT_PARTS[c]
                a = sums[:, col[attempts]]
                out[:, k] = np.where(a > 0, sums[:, col[makes]] / a, np.nan)
            else:
                out[:, k] = sums[:, col[c]]
    return out


def week_records(cats: np.ndarray) -> np.ndarray:
    """All-play W/L/T for one week (teams x 3). A NaN category is a tie."""
    a, b = cats[:, None, :], cats[None, :, :]
    won, lost = (a > b).sum(-1), (a < b).sum(-1)
    np.fill_diagonal(won, 0)
    np.fill_diagonal(lost, 0)
    n = len(cats)
    wins = (won > lost).sum(1)
    losses = (won < lost).sum(1)
    return np.column_stack([wins, losses, (n - 1) - wins - losses])


def project_season(
    lines: pd.DataFrame,
    all_play: pd.DataFrame,
    current_week: int,
    last_week: int,
    as_of,
    rules: InjuryRules = InjuryRules(),
    team_ids=None,
) -> pd.DataFrame:
    """One row per team: actual record so far, projected record for the remaining
    weeks (and its best/worst week), the final record, win % and rank."""
    team_ids = list(team_ids if team_ids is not None else sorted(lines["team_id"].unique()))
    pos = {t: i for i, t in enumerate(team_ids)}
    avail = availability(lines, current_week, as_of, rules)

    stats = avail[SUM_COLUMNS].fillna(0).to_numpy(float)
    owner = np.zeros((len(team_ids), len(avail)))
    owner[avail["team_id"].map(pos).to_numpy(int), np.arange(len(avail))] = 1.0
    back = avail["back_in_week"].to_numpy()

    weeks = list(range(current_week, last_week + 1))
    per_week = np.zeros((len(weeks), len(team_ids), 3))
    for k, week in enumerate(weeks):
        sums = owner @ (stats * (back <= week)[:, None])
        per_week[k] = week_records(_team_lines(sums))

    finished = all_play.loc[
        (all_play["matchup_period"] < current_week) & (all_play["matchup_period"] <= last_week)
    ]
    actual = (
        finished.groupby("team_id")[["ap_wins", "ap_losses", "ap_ties"]]
        .sum()
        .reindex(team_ids, fill_value=0)
        .to_numpy()
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
