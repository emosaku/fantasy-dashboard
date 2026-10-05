"""The Refresh data button's logic (app/refresh.py), with a fake Cloud Run API."""

import datetime as dt

import pytest

from refresh import COOLDOWN, can_refresh, run_ingest

NOW = dt.datetime(2026, 10, 5, 18, 0, tzinfo=dt.UTC)


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


class FakeRunApi:
    """Answers :run with an unfinished operation, then `polls` more unfinished ones,
    then `final`."""

    def __init__(self, polls, final):
        self.polls, self.final, self.calls = polls, final, []

    def post(self, url, json):
        self.calls.append(("POST", url))
        return FakeResponse({"name": "operations/abc", "done": False})

    def get(self, url):
        self.calls.append(("GET", url))
        if self.polls:
            self.polls -= 1
            return FakeResponse({"name": "operations/abc", "done": False})
        return FakeResponse(self.final)


def test_cooldown():
    assert can_refresh(None)
    assert not can_refresh(NOW - COOLDOWN / 2, NOW)
    assert can_refresh(NOW - COOLDOWN, NOW)


def test_run_ingest_waits_for_the_job_to_finish():
    api = FakeRunApi(polls=2, final={"name": "operations/abc", "done": True})
    run_ingest(api, poll_seconds=0)
    assert api.calls[0] == (
        "POST",
        "https://run.googleapis.com/v2/projects/fantasy-dash-emk/locations/us-west1/jobs/espn-ingest:run",
    )
    assert [c[0] for c in api.calls] == ["POST", "GET", "GET", "GET"]


def test_run_ingest_reports_a_failed_run():
    api = FakeRunApi(polls=0, final={"done": True, "error": {"message": "Task failed"}})
    with pytest.raises(RuntimeError, match="Task failed"):
        run_ingest(api, poll_seconds=0)


def test_run_ingest_gives_up_after_the_timeout():
    api = FakeRunApi(polls=10**6, final={})
    with pytest.raises(RuntimeError, match="longer than expected"):
        run_ingest(api, poll_seconds=0, timeout_seconds=0.01)
