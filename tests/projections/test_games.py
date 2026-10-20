import datetime as dt

import pandas as pd
from ingest.projections.games import STATS, from_columns, season_lines, to_columns, window_lines


def game(pid, day, minutes, pts=10.0, season=2027):
    row = {s: 0.0 for s in STATS} | {"MIN": minutes, "PTS": pts}
    return {"player_id": pid, "season": season, "game_date": day} | row


def test_season_lines_skip_games_he_did_not_play():
    games = pd.DataFrame([
        game(1, "2026-10-21", 30, 20), game(1, "2026-10-23", 0, 0),  # DNP
        game(1, "2026-10-25", 34, 26), game(2, "2026-10-21", 12, 4),
    ])  # fmt: skip
    lines = season_lines(games).set_index("player_id")
    assert lines.at[1, "GP"] == 2
    assert (lines.at[1, "MIN"], lines.at[1, "PTS"]) == (64, 46)
    assert lines.at[2, "GP"] == 1


def test_windows_average_only_the_games_inside_them():
    as_of = dt.date(2026, 11, 30)
    games = pd.DataFrame([
        game(1, "2026-10-25", 30, 10),  # season only
        game(1, "2026-11-10", 30, 20),  # last 30
        game(1, "2026-11-20", 30, 30),  # last 15 and 30
        game(1, "2026-11-28", 30, 40),  # every window
        game(1, "2026-12-01", 30, 99),  # after as_of: nowhere
    ])  # fmt: skip
    long = window_lines(games, 2027, as_of)
    pts = long.loc[long["stat"] == "PTS"].set_index("stat_window")["value"]
    gp = long.loc[long["stat"] == "GP"].set_index("stat_window")["value"]
    assert pts.to_dict() == {"season": 25.0, "last_30": 30.0, "last_15": 35.0, "last_7": 40.0}
    assert gp.to_dict() == {"season": 4, "last_30": 3, "last_15": 2, "last_7": 1}


def test_windows_with_no_games_are_left_out():
    games = pd.DataFrame([game(1, "2026-10-25", 30)])
    long = window_lines(games, 2027, dt.date(2026, 12, 31))
    assert set(long["stat_window"]) == {"season"}
    assert window_lines(games, 2028, dt.date(2026, 12, 31)).empty


def test_stat_names_round_trip_through_table_columns():
    frame = pd.DataFrame([{s: 1.0 for s in STATS} | {"GP": 3}])
    columns = to_columns(frame)
    assert {"fg3m", "fg3a", "tov", "gp"} <= set(columns)
    assert not any(c[0].isdigit() for c in columns)
    assert list(from_columns(columns)) == list(frame)
