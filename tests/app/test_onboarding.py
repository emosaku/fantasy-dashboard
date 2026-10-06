"""Registration checks (app/onboarding.py) with a stubbed ESPN response."""

import pytest
from ingest.espn_client import LeagueNotAccessible

import onboarding

# ESPN stat ids: 0 PTS, 6 REB, 3 AST, 11 TO, 19 FG%, 17 3PM, 37 DD (double-doubles).
ITEMS = [{"statId": 0}, {"statId": 6}, {"statId": 11, "isReverseItem": True}, {"statId": 19}]


def espn(scoring_type="H2H_MOST_CATEGORIES", items=ITEMS):
    def fetch(league_id, season, views):
        return {
            "settings": {
                "name": "Test League",
                "scoringSettings": {"scoringType": scoring_type, "scoringItems": items},
            },
            "teams": [
                {"id": 2, "name": "Zebras  "},
                {"id": 1, "location": "Big", "nickname": "Ballers"},
            ],
        }

    return fetch


def refuse(message):
    def fetch(league_id, season, views):
        raise LeagueNotAccessible(message)

    return fetch


def test_public_supported_league_previews():
    out = onboarding.preview(1, 2026, espn())
    assert out["league_name"] == "Test League"
    assert [c["category"] for c in out["categories"]] == ["PTS", "REB", "TO", "FG%"]
    assert [c["lower_is_better"] for c in out["categories"]] == [False, False, True, False]
    assert out["teams"] == [
        {"team_id": 1, "team_name": "Big Ballers"},
        {"team_id": 2, "team_name": "Zebras"},
    ]


def test_private_league_is_refused_with_how_to_fix():
    with pytest.raises(onboarding.CannotRegister, match="viewable to the public"):
        onboarding.preview(1, 2026, refuse("ESPN refused access to this league."))


def test_wrong_id_is_refused():
    msg = "ESPN has no basketball league with that id this season."
    with pytest.raises(onboarding.CannotRegister, match="Check the number"):
        onboarding.preview(1, 2026, refuse(msg))


def test_points_league_is_refused():
    with pytest.raises(onboarding.CannotRegister, match="head-to-head categories"):
        onboarding.preview(1, 2026, espn("H2H_POINTS"))


def test_unsupported_category_is_named():
    with pytest.raises(onboarding.CannotRegister, match="DD"):
        onboarding.preview(1, 2026, espn(items=[*ITEMS, {"statId": 37}]))
