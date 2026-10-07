"""Compare page math. Pure pandas, so both modes are unit-testable without BigQuery.

Teams mode: one line per team for a week or the season, z-scored across the league.
Input is v_team_week_cats (long: team x week x category, with the ratio categories'
two totals). Comparisons use each category's score (lower-is-better flipped), so a
team "wins" turnovers by having fewer.

Players mode: player_compare_frame pulls value/z/rank for 2-4 players from the same
v_player_z pool Player Rankings and the Trade Analyzer use, so a player's rank here
always matches his rank there. Everything works from the league's own category list:
a ratio category's two totals come from v_player_z's num/den, and z is already
flipped for lower-is-better categories.
"""

import pandas as pd

from categories import Category, keys, score


def period_lines(weeks: pd.DataFrame, cats: list[Category], week: int | None) -> pd.DataFrame:
    """One row per team_id, a column per category (the values shown).

    week=None is the season: count categories become per-week averages (teams can
    have played different numbers of weeks), and ratios are recomputed from the
    season's two totals rather than averaged week to week.
    """
    rows = weeks if week is None else weeks.loc[weeks["matchup_period"] == week]
    out = {}
    for cat in cats:
        one = rows.loc[rows["category"] == cat.key]
        by_team = one.groupby("team_id")
        if week is not None:
            out[cat.key] = by_team["value"].first()
        elif cat.kind == "ratio" and one["den"].notna().any():
            sums = by_team[["num", "den"]].sum(min_count=1)
            out[cat.key] = sums["num"] / sums["den"].where(sums["den"] != 0)
        else:
            out[cat.key] = by_team["value"].mean()
    return pd.DataFrame(out).reindex(columns=keys(cats)).astype("float64")


def scores(lines: pd.DataFrame, cats: list[Category]) -> pd.DataFrame:
    """Values -> comparable scores: higher always better."""
    return pd.DataFrame({c.key: score(c, lines[c.key]) for c in cats}, index=lines.index)


def zscores(lines: pd.DataFrame, cats: list[Category]) -> pd.DataFrame:
    """How many league standard deviations each team sits above (better) or below
    the league average, per category. NaN where every team is equal (std 0)."""
    s = scores(lines, cats)
    std = s.std(ddof=0).replace(0, float("nan"))
    return (s - s.mean()) / std


def head_to_head(a: pd.Series, b: pd.Series) -> tuple[int, int, int]:
    """(a's wins, b's wins, ties) across the categories, from scores. A NaN ties."""
    wins = int((a > b).sum())
    losses = int((a < b).sum())
    return wins, losses, len(a) - wins - losses


# --- Players mode ---------------------------------------------------------------------

FRAME_COLUMNS = ["player_id", "category", "value", "num", "den", "z", "rank"]


def window_rows(frame: pd.DataFrame, window: str) -> pd.DataFrame:
    """One stat window's rows of a long player frame (v_player_z or v_player_pool).
    'blended' has no makes/attempts or stat lines of its own (it's a z-layer mix of
    season and projected), so each player takes his season rows once he has any,
    else his projected rows -- the same fallback the Mock trade uses."""
    if window != "blended":
        return frame.loc[frame["stat_window"] == window]
    both = frame.loc[frame["stat_window"].isin(["season", "projected"])]
    has_season = set(both.loc[both["stat_window"] == "season", "player_id"])
    return both.loc[(both["stat_window"] == "season") | ~both["player_id"].isin(has_season)]


def player_compare_frame(
    player_z: pd.DataFrame, player_ids, window: str, cats: list[Category]
) -> pd.DataFrame:
    """One row per (player, category) for `player_ids`: value (per-game stat or
    ratio), num/den (the ratio's two per-game totals, ratio categories only -- NaN
    elsewhere), z, and rank.

    `player_z`: queries.player_z(), unfiltered (every player, every window) -- rank
    comes from the whole pool, the one Player Rankings ranks against, not just the
    players compared here. A player with no stat line in this window gets NaN
    everywhere and no rank (None)."""
    cols = keys(cats)
    z = player_z.loc[player_z["stat_window"] == window]
    pivot = (
        z.pivot_table(index="player_id", columns="category", values="z", aggfunc="first")
        .reindex(columns=cols)
        .fillna(0.0)
    )
    ranks = pivot.rank(ascending=False, method="min").astype(int)
    values = z.pivot_table(index="player_id", columns="category", values="value", aggfunc="first")
    totals = window_rows(player_z, window).drop_duplicates(["player_id", "category"])
    num = totals.pivot_table(index="player_id", columns="category", values="num", aggfunc="first")
    den = totals.pivot_table(index="player_id", columns="category", values="den", aggfunc="first")

    def cell(table: pd.DataFrame, pid, col):
        if pid in table.index and col in table.columns:
            return table.at[pid, col]
        return float("nan")

    rows = []
    for pid in player_ids:
        for cat in cats:
            ratio = cat.kind == "ratio"
            rows.append(
                {
                    "player_id": pid,
                    "category": cat.key,
                    "value": cell(values, pid, cat.key),
                    "num": cell(num, pid, cat.key) if ratio else float("nan"),
                    "den": cell(den, pid, cat.key) if ratio else float("nan"),
                    "z": pivot.at[pid, cat.key] if pid in pivot.index else float("nan"),
                    "rank": ranks.at[pid, cat.key] if pid in ranks.index else None,
                }
            )
    return pd.DataFrame(rows, columns=FRAME_COLUMNS)


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
    value, so a ratio is judged by the same volume-weighted measure as everywhere
    else and a lower-is-better category by its flipped score; an equal z (including
    two players neither of whom has a stat line) is a tie. names: player_id ->
    display name. by: "z" (per game), or "total_score" for season totals (merged in
    from season_totals)."""
    ids = list(dict.fromkeys(frame["player_id"]))
    if len(ids) != 2:
        raise ValueError("head_to_head_verdict needs exactly 2 players")
    a, b = ids
    cols = list(dict.fromkeys(frame["category"]))
    za = frame.loc[frame["player_id"] == a].set_index("category")[by]
    zb = frame.loc[frame["player_id"] == b].set_index("category")[by]
    a_better = [c for c in cols if za[c] > zb[c]]
    b_better = [c for c in cols if zb[c] > za[c]]
    if len(a_better) == len(b_better):
        noun = "category" if len(a_better) == 1 else "categories"
        return f"{names[a]} and {names[b]} are even: {len(a_better)} {noun} each."
    winner, count, loser, loser_better = (
        (a, len(a_better), b, b_better)
        if len(a_better) > len(b_better)
        else (b, len(b_better), a, a_better)
    )
    text = f"{names[winner]} wins {count} of {len(cols)} categories"
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
    player_z: pd.DataFrame, window: str, position: str, cats: list[Category]
) -> pd.DataFrame:
    """The average starting player at `position`, shaped like player_compare_frame's
    rows (player_id = baseline_id(position)): z is the starters' mean z; a count's
    value is their mean per-game stat; a ratio is pooled from their two totals (never
    averaged), with num/den their means; rank is where that z would land among the
    whole pool. Empty if the position has no starters."""
    ids = starter_ids(player_z, window, position)
    if not ids:
        return pd.DataFrame(columns=FRAME_COLUMNS)
    starters = player_compare_frame(player_z, ids, window, cats)
    pool_z = (
        player_z.loc[player_z["stat_window"] == window]
        .pivot_table(index="player_id", columns="category", values="z", aggfunc="first")
        .reindex(columns=keys(cats))
        .fillna(0.0)
    )
    rows = []
    for cat in cats:
        one = starters.loc[starters["category"] == cat.key]
        z = one["z"].mean()
        if cat.kind == "ratio":
            num, den = one["num"].mean(), one["den"].mean()
            value = one["num"].sum() / one["den"].sum() if one["den"].sum() else float("nan")
        else:
            num = den = float("nan")
            value = one["value"].mean()
        rows.append(
            {
                "player_id": baseline_id(position),
                "category": cat.key,
                "value": value,
                "num": num,
                "den": den,
                "z": z,
                "rank": int((pool_z[cat.key] > z).sum()) + 1,
            }
        )
    return pd.DataFrame(rows, columns=FRAME_COLUMNS)


def season_totals(
    player_pool: pd.DataFrame,
    window: str,
    player_ids,
    cats: list[Category],
    groups: dict | None = None,
) -> pd.DataFrame:
    """Season totals for Players mode's totals view: one row per (player, category)
    with total (a count's per-game stat x games played, or the season ratio),
    total_num / total_den (a ratio's two season totals), total_score (what totals
    are ranked and judged by, higher always better: the count total -- negated when
    lower is better -- or for a ratio the extra made over a league-average player on
    the same season volume), total_rank among the whole pool, and gp.

    `player_pool`: queries.player_pool(), long (player x window x stat). Games played
    is the window's own: projected games for 'projected', games so far for 'season'.
    groups maps a baseline id to its member player ids; a baseline's totals are its
    members' averages (a ratio pooled from their totals), ranked where they'd land
    among the pool."""
    wide = window_rows(player_pool, window).pivot_table(
        index="player_id", columns="stat", values="value", aggfunc="first"
    )

    def stat(name: str) -> pd.Series:
        if name in wide.columns:
            return wide[name].fillna(0)
        return pd.Series(0.0, index=wide.index)

    gp = stat("GP")
    totals, scores = {}, {}
    for cat in cats:
        sign = -1 if cat.lower_is_better else 1
        if cat.kind == "ratio":
            made, att = stat(cat.num) * gp, stat(cat.den) * gp
            rate = made.sum() / att.sum() if att.sum() else 0.0
            totals[cat.key] = (made, att)
            scores[cat.key] = sign * (made - rate * att).where(att > 0, 0.0)
        else:
            totals[cat.key] = (stat(cat.num) * gp, None)
            scores[cat.key] = sign * totals[cat.key][0]

    def row(pid, key, members):
        made, att = totals[key]
        total_score = scores[key].reindex(members).mean()
        if att is not None:
            num, den = made.reindex(members).mean(), att.reindex(members).mean()
            attempts = att.reindex(members).sum()
            total = made.reindex(members).sum() / attempts if attempts else float("nan")
        else:
            num = den = float("nan")
            total = made.reindex(members).mean()
        return {
            "player_id": pid,
            "category": key,
            "total": total,
            "total_num": num,
            "total_den": den,
            "total_score": total_score,
            "total_rank": (
                int((scores[key] > total_score).sum()) + 1 if pd.notna(total_score) else None
            ),
            "gp": gp.reindex(members).mean(),
        }

    rows = []
    for pid in player_ids:
        members = [m for m in (groups or {}).get(pid, [pid]) if m in wide.index]
        for cat in cats:
            empty = {"player_id": pid, "category": cat.key}
            rows.append(row(pid, cat.key, members) if members else empty)
    columns = ["player_id", "category", "total", "total_num", "total_den", "total_score",
               "total_rank", "gp"]  # fmt: skip
    return pd.DataFrame(rows, columns=columns)
