"""Registration checks (app/onboarding.py) with a stubbed ESPN response."""

import pytest
from ingest.espn_client import LeagueNotAccessible

import onboarding

# ESPN stat ids: 0 PTS, 6 REB, 3 AST, 11 TO, 19 FG%, 17 3PM, 37 DD (double-doubles).
ITEMS = [{"statId": 0}, {"statId": 6}, {"statId": 11, "isReverseItem": True}, {"statId": 19}]


def espn(scoring_type="H2H_MOST_CATEGORIES", items=ITEMS):
    def fetch(league_id, season, views, cookies=None):
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
    def fetch(league_id, season, views, cookies=None):
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


def test_espns_each_category_name_previews_as_each_category():
    out = onboarding.preview(1, 2026, espn("H2H_CATEGORY"))
    assert out["scoring_type"] == "H2H_EACH_CATEGORY"


def test_private_league_asks_for_a_login():
    with pytest.raises(onboarding.NeedsLogin, match="ESPN login"):
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


# --- Private leagues (Phase 2) -----------------------------------------------------

SWID = "{12345678-ABCD-ABCD-ABCD-1234567890AB}"
OTHER = "{87654321-ABCD-ABCD-ABCD-1234567890AB}"
LOGIN = {"espn_s2": "A" * 60 + "%2B" + "B" * 20, "SWID": SWID}


def private_league(owners_of_team_1=(SWID,), members=(SWID, OTHER)):
    def fetch(league_id, season, views, cookies=None):
        if cookies is None:
            raise LeagueNotAccessible("ESPN refused access to this league.")
        assert cookies == LOGIN  # passed through exactly as cleaned
        data = espn()(league_id, season, views)
        data["teams"][1]["owners"] = list(owners_of_team_1)  # team id 1
        data["teams"][0]["owners"] = [OTHER]
        data["members"] = [{"id": m} for m in members]
        return data

    return fetch


def test_login_finds_the_managers_own_team():
    out = onboarding.preview(1, 2026, private_league(), cookies=LOGIN)
    assert out["private"] and out["my_team"] == 1


def test_a_member_without_a_team_is_allowed_with_no_team():
    out = onboarding.preview(1, 2026, private_league(owners_of_team_1=()), cookies=LOGIN)
    assert out["my_team"] is None


def test_a_login_from_outside_the_league_is_refused():
    fetch = private_league(owners_of_team_1=(), members=(OTHER,))
    with pytest.raises(onboarding.CannotRegister, match="isn't in this league"):
        onboarding.preview(1, 2026, fetch, cookies=LOGIN)


def test_a_refused_login_says_so():
    with pytest.raises(onboarding.CannotRegister, match="didn't accept this login") as error:
        onboarding.preview(1, 2026, refuse("ESPN refused access to this league."), cookies=LOGIN)
    assert not isinstance(error.value, onboarding.NeedsLogin)


def test_clean_cookies_tidies_what_was_pasted_and_keeps_encoding():
    raw_s2 = LOGIN["espn_s2"]
    cleaned = onboarding.clean_cookies(f' "{raw_s2}" ', SWID.strip("{}").lower())
    assert cleaned == LOGIN  # quotes and spaces gone, %2B kept, SWID braced and upper-cased


@pytest.mark.parametrize(
    "s2, swid, problem",
    [("short", SWID, "espn_s2"), ("A" * 60 + " B", SWID, "espn_s2"), ("A" * 80, "nope", "SWID")],
)
def test_clean_cookies_rejects_what_cant_be_a_cookie(s2, swid, problem):
    with pytest.raises(onboarding.CannotRegister, match=problem):
        onboarding.clean_cookies(s2, swid)
