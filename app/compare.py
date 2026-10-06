"""Compare page math.

Teams mode: one stat line per team for a week or the season, z-scored across the
league. v_team_week_cats holds raw weekly values; z-scoring them happens here
because the period being compared (one week, or the season) is a page control, not
something a view can fix in advance.

Players mode: player_compare_frame pulls z/value/rank for 2-4 players from the same
pool v_player_z and v_player_pool already expose for Player Rankings and the Trade
Analyzer, so a player's rank here always matches his rank there. Pure pandas, so
both modes are unit-testable without BigQuery.
"""

import pandas as pd

from categories import COLUMNS, COUNTING, LABELS, PART_COLUMNS, PCT_PARTS, totals


def period_lines(weeks: pd.DataFrame, week: int | None) -> pd.DataFrame:
    """One row per team_id with the 9 categories.

    week=None is the season: counting stats become per-week averages (teams can
    have played different numbers of weeks), and percentages are recomputed from
    season makes/attempts rather than averaged week to week.
    """
    if week is not None:
        return weeks.loc[weeks["matchup_period"] == week].set_index("team_id")[COLUMNS]

    def season_line(team_weeks: pd.DataFrame) -> pd.Series:
        line = totals(team_weeks)
        line[COUNTING] = line[COUNTING] / len(team_weeks)
        return line

    cols = sorted(set(COUNTING) | set(PART_COLUMNS))
    return weeks.groupby("team_id")[cols].apply(season_line)[COLUMNS]


def zscores(lines: pd.DataFrame) -> pd.DataFrame:
    """How many league standard deviations each team sits above or below the
    league average, per category. NaN where every team is equal (std 0)."""
    std = lines.std(ddof=0).replace(0, float("nan"))
    return (lines - lines.mean()) / std


def head_to_head(a: pd.Series, b: pd.Series) -> tuple[int, int, int]:
    """(a's wins, b's wins, ties) across the 9 categories. A NaN compares as a tie."""
    wins = int((a > b).sum())
    losses = int((a < b).sum())
    return wins, losses, len(COLUMNS) - wins - losses


def pool_window_frame(player_pool: pd.DataFrame, window: str) -> pd.DataFrame:
    """v_player_pool has no 'blended' rows of its own (it's a z-layer-only mix of
    season and projected); for makes/attempts under 'blended', use a player's season
    row once he has one, else his projected row -- the same fallback the Mock
    trade's per_game_lines() uses for the same reason."""
    if window != "blended":
        return player_pool.loc[player_pool["stat_window"] == window]
    both = player_pool.loc[player_pool["stat_window"].isin(["season", "projected"])]
    return both.sort_values("stat_window", ascending=False).drop_duplicates("player_id")


def player_compare_frame(
    player_z: pd.DataFrame, player_pool: pd.DataFrame, player_ids, window: str
) -> pd.DataFrame:
    """One row per (player, category) for `player_ids`, for the Players mode of the
    Compare page: value (per-game stat, or percentage), num/den (makes/attempts,
    the three percentage categories only -- NaN elsewhere), z, and rank.

    `player_z`/`player_pool`: queries.player_z() / queries.player_pool(), unfiltered
    (every player, every window) -- rank has to come from the whole pool, the same
    one Player Rankings ranks against, not just the players being compared here.
    A player missing from the pool (no stat line in this window) gets NaN/None
    everywhere except rank, which is left out entirely (None)."""
    z = player_z.loc[player_z["stat_window"] == window]
    pool = pool_window_frame(player_pool, window).set_index("player_id")

    pivot = (
        z.pivot_table(index="player_id", columns="category", values="z", aggfunc="first")
        .reindex(columns=COLUMNS)
        .fillna(0.0)
    )
    ranks = pivot.rank(ascending=False, method="min").astype(int)
    values = z.pivot_table(index="player_id", columns="category", values="value", aggfunc="first")

    rows = []
    for pid in player_ids:
        for col in COLUMNS:
            if col in PCT_PARTS and pid in pool.index:
                makes_col, attempts_col = PCT_PARTS[col]
                num, den = pool.at[pid, makes_col], pool.at[pid, attempts_col]
            else:
                num = den = float("nan")
            rows.append(
                {
                    "player_id": pid,
                    "category": col,
                    "value": values.at[pid, col] if pid in values.index else float("nan"),
                    "num": num,
                    "den": den,
                    "z": pivot.at[pid, col] if pid in pivot.index else float("nan"),
                    "rank": ranks.at[pid, col] if pid in ranks.index else None,
                }
            )
    return pd.DataFrame(rows)


def _and_join(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def head_to_head_verdict(frame: pd.DataFrame, names: dict) -> str:
    """One sentence for exactly 2 players (player_compare_frame's output): who wins
    more categories and what the other is better in -- "Player A wins 6 of 9
    categories; Player B is better in FT%, 3PT%, and STL." Counts by z, not the raw
    value, so a percentage is judged by the same volume-weighted measure as
    everywhere else; a category with equal z (including two players neither of whom
    have a stat line) is a tie and favors neither. names: player_id -> display name."""
    ids = list(dict.fromkeys(frame["player_id"]))
    if len(ids) != 2:
        raise ValueError("head_to_head_verdict needs exactly 2 players")
    a, b = ids
    za = frame.loc[frame["player_id"] == a].set_index("category")["z"]
    zb = frame.loc[frame["player_id"] == b].set_index("category")["z"]
    a_better = [LABELS[c] for c in COLUMNS if za[c] > zb[c]]
    b_better = [LABELS[c] for c in COLUMNS if zb[c] > za[c]]
    if len(a_better) == len(b_better):
        return f"{names[a]} and {names[b]} are even: {len(a_better)} categories each."
    winner, count, loser, loser_better = (
        (a, len(a_better), b, b_better)
        if len(a_better) > len(b_better)
        else (b, len(b_better), a, a_better)
    )
    text = f"{names[winner]} wins {count} of {len(COLUMNS)} categories"
    if loser_better:
        text += f"; {names[loser]} is better in {_and_join(loser_better)}."
    else:
        text += "."
    return text
