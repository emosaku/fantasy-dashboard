"""Per-game player rows -> the season lines the model reads and the stat windows the
pages read.

A game row is one player in one game: player_id, season, game_date, and his box score
line in League Lab's stat names (MIN, PTS, REB, ... from ingest.catalog). A row with no
minutes is a game he didn't play (a DNP or inactive) and is dropped, so GP counts only
games he actually played -- the same rule ESPN's games played follows.

Beyond the 15 core stats, the stat windows carry the extra stats a league can score
(docs/whopDocs/bonus-stats.md): bonuses that only exist game by game (double-, triple-
and quadruple-doubles; fouling out) counted from each box score, personal fouls, and
missed shots (attempts minus makes). Their per-game average is the share of games with
the bonus: 0.6 DD = a double-double in 60% of his games.
"""

import datetime as dt

import pandas as pd

from ingest.catalog import COUNT, EXTRA_COUNT

STATS = list(COUNT)  # the 15 per-game stats League Lab uses, MIN included
BONUS = ["DD", "TD", "QD", "PF", "DQ"]  # counted per game; projected from his own rate
MISSES = {"FGMI": ("FGA", "FGM"), "FTMI": ("FTA", "FTM"), "3PMI": ("3PA", "3PM")}
EXTRA = [*BONUS, *MISSES]  # every stat beyond the 15 we can count
assert set(EXTRA) == set(EXTRA_COUNT)
DOUBLE_STATS = ["PTS", "REB", "AST", "STL", "BLK"]  # 10+ in two of these = a double-double
FOUL_OUT = 6
WINDOW_DAYS = {"last_30": 30, "last_15": 15, "last_7": 7}

# League Lab's stat names <-> the BigQuery columns (BallDontLie's names; a BigQuery
# column can't start with a digit). GP is "gp" in the projections table.
COLUMNS = {"MIN": "min", "PTS": "pts", "REB": "reb", "OREB": "oreb", "DREB": "dreb",
           "AST": "ast", "STL": "stl", "BLK": "blk", "TO": "tov", "FGM": "fgm",
           "FGA": "fga", "3PM": "fg3m", "3PA": "fg3a", "FTM": "ftm", "FTA": "fta",
           "GP": "gp", "PF": "pf", "DD": "dd", "TD": "td", "QD": "qd", "DQ": "dq"}  # fmt: skip
assert set(COLUMNS) == set(STATS) | {"GP"} | set(BONUS)


def from_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """A table's columns renamed to League Lab's stat names."""
    return frame.rename(columns={v: k for k, v in COLUMNS.items()})


def to_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """League Lab's stat names renamed to the table's columns."""
    return frame.rename(columns=COLUMNS)


def with_misses(lines: pd.DataFrame) -> pd.DataFrame:
    """Missed shots added to per-game (or per-game average) lines: attempts - makes."""
    out = lines.copy()
    for miss, (attempts, makes) in MISSES.items():
        if attempts in out and makes in out:
            out[miss] = out[attempts] - out[makes]
    return out


def with_bonus(games: pd.DataFrame) -> pd.DataFrame:
    """Game rows with each game's bonuses (1 or 0) and misses added. A game without a
    foul count (loaded before fouls were) has no PF or DQ value."""
    out = with_misses(games)
    tens = (out[DOUBLE_STATS].fillna(0) >= 10).sum(axis=1)
    for name, count in (("DD", 2), ("TD", 3), ("QD", 4)):
        out[name] = (tens >= count).astype(float)
    fouls = out["PF"] if "PF" in out else pd.Series(float("nan"), index=out.index)
    out["PF"] = fouls
    out["DQ"] = (fouls >= FOUL_OUT).astype(float).where(fouls.notna())
    return out


def played(games: pd.DataFrame) -> pd.DataFrame:
    """The rows where the player was on the floor."""
    return games.loc[games["MIN"].fillna(0) > 0]


def season_lines(games: pd.DataFrame) -> pd.DataFrame:
    """One row per player x season: GP and the season total of every stat."""
    rows = played(games)
    totals = rows.groupby(["player_id", "season"])[STATS].sum()
    totals.insert(0, "GP", rows.groupby(["player_id", "season"]).size())
    return totals.reset_index()


def _per_game(rows: pd.DataFrame) -> pd.DataFrame:
    grouped = rows.groupby("player_id")
    out = grouped[[*STATS, *EXTRA]].mean()
    out.insert(0, "GP", grouped.size())
    return out


def window_lines(games: pd.DataFrame, season: int, as_of: dt.date) -> pd.DataFrame:
    """Per-game averages in League Lab's long format (player_id, stat_window, stat,
    value): the whole season so far, and the games in the last 30, 15 and 7 days up to
    and including `as_of`. GP is the games in the window. The extra stats (EXTRA) ride
    along."""
    rows = with_bonus(played(games.loc[games["season"] == season]))
    dates = pd.to_datetime(rows["game_date"]).dt.date
    windows = {"season": rows.loc[dates <= as_of]}
    for name, days in WINDOW_DAYS.items():
        windows[name] = rows.loc[(dates <= as_of) & (dates > as_of - dt.timedelta(days=days))]
    frames = []
    for name, subset in windows.items():
        if subset.empty:
            continue
        long = (
            _per_game(subset)
            .reset_index()
            .melt(id_vars="player_id", var_name="stat", value_name="value")
            .dropna(subset=["value"])
        )
        frames.append(long.assign(stat_window=name))
    if not frames:
        return pd.DataFrame(columns=["player_id", "stat_window", "stat", "value"])
    return pd.concat(frames, ignore_index=True)[["player_id", "stat_window", "stat", "value"]]
