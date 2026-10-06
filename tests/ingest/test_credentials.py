"""Reading a private league's ESPN login in the ingest job (ingest/credentials.py)."""

import base64
import json
from types import SimpleNamespace

import pytest
from ingest.credentials import NeedsLogin, cookies_for

LOGIN = {"espn_s2": "s2", "SWID": "{X}"}


class FakeSession:
    def __init__(self, status=200):
        self.status, self.urls = status, []

    def get(self, url):
        self.urls.append(url)
        body = {"payload": {"data": base64.b64encode(json.dumps(LOGIN).encode()).decode()}}
        return SimpleNamespace(
            status_code=self.status, json=lambda: body, raise_for_status=lambda: None
        )


def test_public_league_needs_no_cookies():
    assert cookies_for({"credentials": "public"}, "p") is None
    assert cookies_for({}, "p") is None


def test_saved_login_is_read_from_its_secret():
    session = FakeSession()
    assert cookies_for({"credentials": "secret:league-9-espn"}, "p", session) == LOGIN
    assert session.urls == [
        "https://secretmanager.googleapis.com/v1/projects/p/secrets/league-9-espn/versions/latest:access"
    ]


@pytest.mark.parametrize(
    "league, status",
    [({"credentials": "removed"}, 200), ({"credentials": "secret:league-9-espn"}, 404)],
)
def test_removed_or_missing_login_waits_for_the_commissioner(league, status):
    with pytest.raises(NeedsLogin):
        cookies_for(league, "p", FakeSession(status))
