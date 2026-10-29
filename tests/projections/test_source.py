import datetime as dt

import pytest
import requests
from ingest.projections.source import (
    Client,
    game_rows,
    games_left,
    injury_rows,
    minutes,
    player_rows,
)


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code, self.payload = status, payload or {}

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


class FakeSession:
    def __init__(self, responses):
        self.responses, self.headers, self.calls = list(responses), {}, []

    def get(self, url, params, timeout):
        self.calls.append((url, dict(params)))
        return self.responses.pop(0)


class Clock:
    def __init__(self):
        self.now, self.slept = 0.0, []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def client(responses):
    clock = Clock()
    session = FakeSession(responses)
    return Client("KEY", session, sleep=clock.sleep, clock=clock), session, clock


def test_pages_follow_the_cursor_and_send_the_key():
    bdl, session, _ = client(
        [
            FakeResponse(200, {"data": [1, 2], "meta": {"next_cursor": 9}}),
            FakeResponse(200, {"data": [3], "meta": {}}),
        ]
    )
    assert list(bdl.pages("stats", {"seasons[]": 2025})) == [1, 2, 3]
    assert session.headers["Authorization"] == "KEY"
    assert "cursor" not in session.calls[0][1] and session.calls[1][1]["cursor"] == 9
    assert session.calls[0][1]["per_page"] == 100


def test_requests_are_spaced_under_the_rate_limit():
    bdl, _, clock = client([FakeResponse(200, {"data": []})] * 3)
    for _ in range(3):
        bdl._get("players", {})
    assert clock.slept == [pytest.approx(1.05)] * 2


def test_rate_limits_are_retried_and_bad_requests_are_not():
    bdl, session, _ = client([FakeResponse(429), FakeResponse(200, {"data": [1]})])
    assert bdl._get("stats", {})["data"] == [1]
    bdl, _, _ = client([FakeResponse(401)])
    with pytest.raises(requests.HTTPError):
        bdl._get("stats", {})


def test_seasons_are_translated_to_balldontlies_start_year():
    bdl, session, _ = client([FakeResponse(200, {"data": []})])
    bdl.game_stats(2026)
    assert session.calls[0][1]["seasons[]"] == 2025
    assert session.calls[0][1]["season_type"] == "regular"


def test_minutes_parse_every_format():
    assert [minutes(v) for v in ("30", "00", "", None, "30:30")] == [30.0, 0.0, 0.0, 0.0, 30.5]


def raw(pid, game, mins, pts=10):
    return {
        "player": {"id": pid},
        "team": {"abbreviation": "DEN"},
        "min": mins,
        "pts": pts,
        "turnover": 2,
        "fg3m": 1,
        "game": {"id": game, "season": 2025, "date": "2025-01-02"},
    }


def test_game_rows_use_league_lab_seasons_and_drop_repeats():
    at = dt.datetime(2026, 10, 19, tzinfo=dt.UTC)
    rows = game_rows([raw(1, 7, "30"), raw(1, 7, "30"), raw(2, 7, "00", 0)], at)
    assert len(rows) == 2
    first = rows.iloc[0]
    assert (first["season"], first["game_date"], first["team"]) == (
        2026,
        dt.date(2025, 1, 2),
        "DEN",
    )
    assert (first["min"], first["pts"], first["tov"], first["fg3m"], first["ast"]) == (
        30,
        10,
        2,
        1,
        0,
    )


def test_player_rows_start_without_birth_dates_or_espn_ids():
    at = dt.datetime(2026, 10, 19, tzinfo=dt.UTC)
    rows = player_rows(
        [
            {
                "id": 246,
                "first_name": "Nikola",
                "last_name": "Jokic",
                "position": "C",
                "draft_year": 2014,
                "team": {"abbreviation": "DEN"},
            }
        ],
        at,
    )
    row = rows.iloc[0]
    assert (row["player_name"], row["draft_year"], row["team"]) == ("Nikola Jokic", 2014, "DEN")
    assert row["birth_date"] is None and row["espn_player_id"] is None


def test_unfinished_games_are_left_out():
    at = dt.datetime(2026, 10, 29, tzinfo=dt.UTC)
    live = raw(3, 8, "20")
    live["game"] |= {"status": "3rd Qtr", "status_state": "in"}
    done = raw(4, 9, "20")
    done["game"] |= {"status": "Final", "status_state": "final"}
    assert list(game_rows([live, done], at)["player_id"]) == [4]


def test_players_by_id_ask_in_batches_of_a_hundred():
    bdl, session, _ = client([FakeResponse(200, {"data": [{"id": 1}]}),
                              FakeResponse(200, {"data": [{"id": 150}]})])  # fmt: skip
    assert [p["id"] for p in bdl.players(list(range(1, 151)))] == [1, 150]
    assert len(session.calls[0][1]["player_ids[]"]) == 100


def test_games_left_count_both_teams_after_the_day():
    def game(day, home, away):
        return {"date": day, "postseason": False, "home_team": {"abbreviation": home},
                "visitor_team": {"abbreviation": away}}  # fmt: skip

    schedule = [game("2026-10-28", "DEN", "LAL"), game("2026-10-29", "DEN", "BOS"),
                game("2026-10-30", "LAL", "BOS")]  # fmt: skip
    left = games_left(schedule, dt.date(2026, 10, 28))
    assert left.to_dict() == {"BOS": 2, "DEN": 1, "LAL": 1}


def test_injuries_keep_status_and_date_but_not_the_notes():
    at = dt.datetime(2026, 10, 29, tzinfo=dt.UTC)
    records = [
        {"player": {"id": 1}, "status": "Out", "return_date": "2026-11-04",
         "description": "Someone's reporting."},
        {"player": {"id": 2}, "status": "Questionable", "return_date": None},
        {"player": {"id": 3}, "status": "Probable"},
    ]  # fmt: skip
    rows = injury_rows(records, at).set_index("player_id")
    assert list(rows["status"]) == ["OUT", "DAY_TO_DAY", "ACTIVE"]
    assert rows.at[1, "return_date"] == dt.date(2026, 11, 4)
    assert rows.at[2, "source_status"] == "Questionable"
    assert "description" not in rows
