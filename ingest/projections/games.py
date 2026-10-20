"""Per-game player rows -> the season lines the model reads and the stat windows the
pages read.

A game row is one player in one game: player_id, season, game_date, and his box score
line in League Lab's stat names (MIN, PTS, REB, ... from ingest.catalog). A row with no
minutes is a game he didn't play (a DNP or inactive) and is dropped, so GP counts only
games he actually played -- the same rule ESPN's games played follows.
"""

import datetime as dt

import pandas as pd

from ingest.catalog import COUNT

STATS = list(COUNT)  # the 15 per-game stats League Lab uses, MIN included
WINDOW_DAYS = {"last_30": 30, "last_15": 15, "last_7": 7}

# League Lab's stat names <-> the BigQuery columns (BallDontLie's names; a BigQuery
# column can't start with a digit). GP is "gp" in the projections table.
COLUMNS = {"MIN": "min", "PTS": "pts", "REB": "reb", "OREB": "oreb", "DREB": "dreb",
           "AST": "ast", "STL": "stl", "BLK": "blk", "TO": "tov", "FGM": "fgm",
           "FGA": "fga", "3PM": "fg3m", "3PA": "fg3a", "FTM": "ftm", "FTA": "fta",
           "GP": "gp"}  # fmt: skip
assert set(COLUMNS) == set(STATS) | {"GP"}


def from_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """A table's columns renamed to League Lab's stat names."""
    return frame.rename(columns={v: k for k, v in COLUMNS.items()})


def to_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """League Lab's stat names renamed to the table's columns."""
    return frame.rename(columns=COLUMNS)


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
    out = grouped[STATS].mean()
    out.insert(0, "GP", grouped.size())
    return out


def window_lines(games: pd.DataFrame, season: int, as_of: dt.date) -> pd.DataFrame:
    """Per-game averages in League Lab's long format (player_id, stat_window, stat,
    value): the whole season so far, and the games in the last 30, 15 and 7 days up to
    and including `as_of`. GP is the games in the window."""
    rows = played(games.loc[games["season"] == season])
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
        )
        frames.append(long.assign(stat_window=name))
    if not frames:
        return pd.DataFrame(columns=["player_id", "stat_window", "stat", "value"])
    return pd.concat(frames, ignore_index=True)[["player_id", "stat_window", "stat", "value"]]
