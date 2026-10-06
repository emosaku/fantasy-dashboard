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


def head_to_head_verdict(frame: pd.DataFrame, names: dict, by: str = "z") -> str:
    """One sentence for exactly 2 players (player_compare_frame's output): who wins
    more categories and what the other is better in -- "Player A wins 6 of 9
    categories; Player B is better in FT%, 3PT%, and STL." Counts by z, not the raw
    value, so a percentage is judged by the same volume-weighted measure as
    everywhere else; a category with equal z (including two players neither of whom
    have a stat line) is a tie and favors neither. names: player_id -> display name.
    by: the column compared -- "z" (per game), or "total_score" for season totals
    (merged in from season_totals)."""
    ids = list(dict.fromkeys(frame["player_id"]))
    if len(ids) != 2:
        raise ValueError("head_to_head_verdict needs exactly 2 players")
    a, b = ids
    za = frame.loc[frame["player_id"] == a].set_index("category")[by]
    zb = frame.loc[frame["player_id"] == b].set_index("category")[by]
    a_better = [LABELS[c] for c in COLUMNS if za[c] > zb[c]]
    b_better = [LABELS[c] for c in COLUMNS if zb[c] > za[c]]
    if len(a_better) == len(b_better):
        noun = "category" if len(a_better) == 1 else "categories"
        return f"{names[a]} and {names[b]} are even: {len(a_better)} {noun} each."
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


# --- Players mode: position baselines and season totals ------------------------------

POSITIONS = ["PG", "SG", "SF", "PF", "C"]
BENCH_SLOTS = {"BE", "IR"}


def baseline_id(position: str) -> int:
    """A baseline's id in the compare frame: negative, so it can't collide with a
    real player id."""
    return -(POSITIONS.index(position) + 1)


def starter_ids(player_z: pd.DataFrame, window: str, position: str) -> list[int]:
    """The players behind "average starting <position>": rostered, in an active lineup
    slot (not bench or IR), whose position is `position`, in this stat window."""
    z = player_z.loc[player_z["stat_window"] == window].drop_duplicates("player_id")
    starters = z.loc[
        z["team_id"].notna()
        & z["lineup_slot"].notna()
        & ~z["lineup_slot"].isin(BENCH_SLOTS)
        & (z["position"] == position)
    ]
    return [int(p) for p in starters["player_id"]]


def position_baseline(
    player_z: pd.DataFrame, player_pool: pd.DataFrame, window: str, position: str
) -> pd.DataFrame:
    """The average starting player at `position`, shaped like player_compare_frame's
    rows (player_id = baseline_id(position)): z is the starters' mean z; a counting
    value is their mean per-game stat; a percentage is pooled from their makes and
    attempts (never averaged), with num/den their mean makes/attempts; rank is where
    that z would land among the whole pool. Empty if the position has no starters."""
    ids = starter_ids(player_z, window, position)
    if not ids:
        return pd.DataFrame(columns=["player_id", "category", "value", "num", "den", "z", "rank"])
    starters = player_compare_frame(player_z, player_pool, ids, window)
    pool_z = (
        player_z.loc[player_z["stat_window"] == window]
        .pivot_table(index="player_id", columns="category", values="z", aggfunc="first")
        .reindex(columns=COLUMNS)
        .fillna(0.0)
    )
    rows = []
    for col in COLUMNS:
        cat = starters.loc[starters["category"] == col]
        z = cat["z"].mean()
        if col in PCT_PARTS:
            num, den = cat["num"].mean(), cat["den"].mean()
            value = cat["num"].sum() / cat["den"].sum() if cat["den"].sum() else float("nan")
        else:
            num = den = float("nan")
            value = cat["value"].mean()
        rows.append(
            {
                "player_id": baseline_id(position),
                "category": col,
                "value": value,
                "num": num,
                "den": den,
                "z": z,
                "rank": int((pool_z[col] > z).sum()) + 1,
            }
        )
    return pd.DataFrame(rows)


def season_totals(
    player_pool: pd.DataFrame, window: str, player_ids, groups: dict | None = None
) -> pd.DataFrame:
    """Season totals for Players mode's totals view: one row per (player, category)
    with total (counting stat x games played, or the season percentage), total_num /
    total_den (season makes/attempts), total_score (what totals are ranked and judged
    by: the counting total, or for a percentage the extra makes over a league-average
    shooter on the same season volume), total_rank among the whole pool, and gp.

    Games played is the window's own: projected games for 'projected', games so far
    for 'season'. groups maps a baseline id to its member player ids; a baseline's
    totals are its members' averages (a percentage pooled from their makes and
    attempts), ranked where they'd land among the pool."""
    pool = pool_window_frame(player_pool, window).set_index("player_id")
    gp = pool["gp"].fillna(0)
    totals, scores = {}, {}
    for col in COLUMNS:
        if col in PCT_PARTS:
            makes_col, attempts_col = PCT_PARTS[col]
            makes, attempts = pool[makes_col].fillna(0) * gp, pool[attempts_col].fillna(0) * gp
            rate = makes.sum() / attempts.sum() if attempts.sum() else 0.0
            totals[col] = (makes, attempts)
            scores[col] = (makes - rate * attempts).where(attempts > 0, 0.0)
        else:
            totals[col] = (pool[col].fillna(0) * gp, None)
            scores[col] = totals[col][0]

    def row(pid, col, members):
        made, att = totals[col]
        score = scores[col].reindex(members).mean()
        if att is not None:
            num, den = made.reindex(members).mean(), att.reindex(members).mean()
            attempts = att.reindex(members).sum()
            total = made.reindex(members).sum() / attempts if attempts else float("nan")
        else:
            num = den = float("nan")
            total = made.reindex(members).mean()
        return {
            "player_id": pid,
            "category": col,
            "total": total,
            "total_num": num,
            "total_den": den,
            "total_score": score,
            "total_rank": int((scores[col] > score).sum()) + 1 if pd.notna(score) else None,
            "gp": gp.reindex(members).mean(),
        }

    rows = []
    for pid in player_ids:
        members = (groups or {}).get(pid, [pid])
        members = [m for m in members if m in pool.index]
        for col in COLUMNS:
            if not members:
                rows.append({"player_id": pid, "category": col})
                continue
            rows.append(row(pid, col, members))
    return pd.DataFrame(rows)
