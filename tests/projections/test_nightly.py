import datetime as dt

import pandas as pd
from ingest.projections.nightly import (
    BLENDED,
    blended_rows,
    default_as_of,
    history_rows,
    links,
    load_start,
    rookie_prior,
    teams_now,
)
from ingest.projections.run import MODEL_VERSION

from tests.projections.synthetic import season_row

NOW = dt.datetime(2026, 10, 29, 12, tzinfo=dt.UTC)


def test_as_of_is_yesterday_on_the_nbas_calendar():
    assert default_as_of(NOW) == dt.date(2026, 10, 28)
    late = dt.datetime(2026, 10, 30, 3, tzinfo=dt.UTC)  # still the 29th in New York
    assert default_as_of(late) == dt.date(2026, 10, 28)


def test_loads_go_back_a_few_days_or_take_the_whole_season():
    assert load_start(None, dt.date(2026, 10, 28)) is None
    assert load_start(dt.date(2026, 10, 27), dt.date(2026, 10, 28)) == dt.date(2026, 10, 24)


def test_links_never_reuse_an_espn_id_and_skip_unknown_names():
    players = pd.DataFrame(
        [(1, "Cooper Flagg", 2025), (2, "Nobody Known", 2026)],
        columns=["player_id", "player_name", "draft_year"],
    )
    espn = pd.DataFrame([{"espn_player_id": 5100, "name": "Cooper Flagg"}])
    found = links(players, espn)
    assert found.to_dict("records") == [{"player_id": 1, "espn_player_id": 5100}]


def history():
    """Last season: two veterans; this season so far: one of them, and a rookie with
    one huge night."""
    return pd.DataFrame([
        season_row(1, 2026, 70, 2100, PTS=1400, AST=350),
        season_row(2, 2026, 60, 1200, PTS=480, AST=120),
        season_row(1, 2027, 5, 175, PTS=200, AST=25),
        season_row(9, 2027, 1, 38, PTS=45, AST=2),
    ])  # fmt: skip


def preseason():
    return pd.DataFrame([
        {**season_row(1, 2027, 70, 34), "PTS": 22.0, "AST": 5.0, "age": 27.0},
        {**season_row(2, 2027, 60, 20), "PTS": 8.0, "AST": 2.0, "age": 31.0},
    ]).drop(columns="season")  # fmt: skip


def test_a_rookie_starts_from_a_league_average_line():
    line = rookie_prior(history(), 2027, [9]).set_index("player_id")
    assert line.at[9, "MIN"] == 18.0
    league_rate = (1400 + 480) / (2100 + 1200)
    assert abs(line.at[9, "PTS"] - league_rate * 18) < 1e-9


def test_blended_rows_move_with_the_season_and_keep_season_games():
    teams = pd.Series({1: "DEN", 2: "LAL", 9: "SAS"})
    left = pd.Series({"DEN": 75, "LAL": 76, "SAS": 77})
    rows = blended_rows(history(), preseason(), teams, left, 2027, NOW).set_index("player_id")
    assert set(rows.index) == {1, 2, 9}
    table = {"season", "made_at", "model_version", "kind", "gp", "min", "pts", "reb", "oreb",
             "dreb", "ast", "stl", "blk", "tov", "fgm", "fga", "fg3m", "fg3a", "ftm", "fta",
             "age", "history_minutes"}  # fmt: skip
    assert table <= set(rows.columns) and (rows["season"] == 2027).all()
    assert (rows["kind"] == BLENDED).all() and (rows["model_version"] == MODEL_VERSION).all()
    # player 1 scored 40 a game in 5 games: up from 22, but nowhere near 40
    assert 22 < rows.at[1, "pts"] < 26
    assert abs(rows.at[1, "gp"] - (5 + 75 * 70 / 82)) < 1e-9  # played + his share of what's left
    assert rows.at[2, "pts"] == 8.0  # no games yet: the preseason line
    assert rows.at[9, "pts"] < 20  # one 45-point night isn't a 45-point projection
    assert rows.at[1, "age"] == 27.0


def test_a_player_without_a_team_has_no_games_left():
    rows = blended_rows(history(), preseason(), pd.Series({1: "DEN"}), pd.Series({"DEN": 75}),
                        2027, NOW).set_index("player_id")  # fmt: skip
    assert rows.at[2, "gp"] == 0


def test_teams_follow_his_latest_game():
    games = pd.DataFrame({"player_id": [1, 1], "season": [2027, 2027], "team": ["DEN", "LAL"],
                          "game_date": [dt.date(2026, 10, 22), dt.date(2026, 10, 27)]})  # fmt: skip
    players = pd.DataFrame({"player_id": [1, 2], "team": ["DEN", "BOS"]})
    assert teams_now(games, players, 2027).to_dict() == {1: "LAL", 2: "BOS"}


def test_history_is_games_played_by_espn_id_for_past_seasons():
    players = pd.DataFrame({"player_id": [1, 2], "espn_player_id": [3112335, None]})
    rows = history_rows(history(), players, 2027, 3, NOW)
    assert rows[["player_id", "history_season", "games_played"]].to_dict("records") == [
        {"player_id": 3112335, "history_season": 2026, "games_played": 70.0}
    ]


def test_no_rookies_is_fine():
    veterans = history().loc[lambda h: h["player_id"] != 9]
    rows = blended_rows(veterans, preseason(), pd.Series({1: "DEN", 2: "LAL"}),
                        pd.Series({"DEN": 75, "LAL": 76}), 2027, NOW)  # fmt: skip
    assert set(rows["player_id"]) == {1, 2}


def test_blended_rows_carry_projected_bonuses():
    from ingest.projections.bonus import bonus_rates

    recent = history().assign(REB=0.0)  # season lines stand in for games here
    rates, league = bonus_rates(recent.assign(PF=3.0), 2027)
    rows = blended_rows(history(), preseason(), pd.Series({1: "DEN", 2: "LAL", 9: "SAS"}),
                        pd.Series({"DEN": 75, "LAL": 76, "SAS": 77}), 2027, NOW,
                        (rates, league)).set_index("player_id")  # fmt: skip
    assert {"dd", "td", "qd", "pf", "dq"} <= set(rows.columns)
    assert rows["pf"].notna().all()


def test_the_days_injury_list_is_kept_with_its_date():
    from ingest.projections.nightly import injury_history_rows
    from ingest.projections.source import injury_rows

    rows = injury_rows([{"player": {"id": 1}, "status": "Out", "return_date": "2026-11-04"}], NOW)
    kept = injury_history_rows(rows, dt.date(2026, 10, 29))
    assert kept.to_dict("records") == [{
        "player_id": 1, "status": "OUT", "source_status": "Out",
        "return_date": dt.date(2026, 11, 4), "snapshot_date": dt.date(2026, 10, 29),
    }]  # fmt: skip


def test_links_fall_back_to_team_for_the_rest():
    players = pd.DataFrame(
        [(1, "Cooper Flagg", 2025, "DAL"), (2, "Jaylin Williams", 2022, "OKC"),
         (3, "David Jones", None, "SAS")],
        columns=["player_id", "player_name", "draft_year", "team"],
    )  # fmt: skip
    espn = pd.DataFrame(
        [(5100, "Cooper Flagg", "DAL"), (4431776, "Jaylin Williams", None),
         (4432823, "Jaylin Williams", "OKC"), (4713010, "David Jones Garcia", "SAS")],
        columns=["espn_player_id", "name", "team"],
    )  # fmt: skip
    got = dict(links(players, espn).itertuples(index=False))
    assert got == {1: 5100, 2: 4432823, 3: 4713010}
