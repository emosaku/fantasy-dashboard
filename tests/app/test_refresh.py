"""The Refresh data button's logic (app/refresh.py), with a fake Cloud Run API."""

import datetime as dt

import pytest

from refresh import COOLDOWN, can_refresh, run_ingest

NOW = dt.datetime(2026, 10, 5, 18, 0, tzinfo=dt.UTC)


class FakeResponse:
    def raise_for_status(self):
        pass


class FakeRunApi:
    def __init__(self):
        self.calls = []

    def post(self, url, json):
        self.calls.append(url)
        return FakeResponse()


def finishes_after(checks):
    """A finished() that turns True on its `checks`-th call."""
    state = {"n": 0}

    def finished():
        state["n"] += 1
        return state["n"] >= checks

    return finished


def test_cooldown():
    assert can_refresh(None)
    assert not can_refresh(NOW - COOLDOWN / 2, NOW)
    assert can_refresh(NOW - COOLDOWN, NOW)


def test_run_ingest_starts_the_job_and_waits_for_the_data():
    api = FakeRunApi()
    finished = finishes_after(3)
    run_ingest(finished, api, poll_seconds=0)
    assert api.calls == [
        "https://run.googleapis.com/v2/projects/fantasy-dash-emk/locations/us-west1/jobs/espn-ingest:run"
    ]


def test_run_ingest_gives_up_after_the_timeout():
    with pytest.raises(RuntimeError, match="longer than expected"):
        run_ingest(lambda: False, FakeRunApi(), poll_seconds=0, timeout_seconds=0.01)
