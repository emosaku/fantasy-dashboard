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


def test_bonuses_are_counted_game_by_game():
    from ingest.projections.games import with_bonus

    games = pd.DataFrame([
        game(1, "2026-10-21", 36, 25) | {"REB": 12.0, "PF": 6.0},  # double-double, fouled out
        game(1, "2026-10-23", 36, 15) | {"REB": 11, "AST": 10, "PF": 2.0},  # triple-double
        game(1, "2026-10-25", 36, 9) | {"REB": 30, "PF": 1.0},  # 9 points: not one
    ])  # fmt: skip
    games["FGA"], games["FGM"] = 20.0, 8.0
    rows = with_bonus(games)
    assert list(rows["DD"]) == [1, 1, 0]  # a triple-double is also a double-double
    assert list(rows["TD"]) == [0, 1, 0]
    assert list(rows["DQ"]) == [1, 0, 0]
    assert list(rows["FGMI"]) == [12, 12, 12]


def test_windows_carry_bonus_rates_and_skip_fouls_never_loaded():
    games = pd.DataFrame([
        game(1, "2026-10-21", 36, 25) | {"REB": 12.0},
        game(1, "2026-10-23", 36, 15),
    ])  # fmt: skip
    long = window_lines(games, 2027, dt.date(2026, 10, 25))
    season = long.loc[long["stat_window"] == "season"].set_index("stat")["value"]
    assert season["DD"] == 0.5 and season["TD"] == 0
    assert "PF" not in season and "DQ" not in season  # no foul counts: no row, not 0
