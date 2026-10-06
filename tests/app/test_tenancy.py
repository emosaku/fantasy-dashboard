"""League Lab's tenancy rules (app/tenancy.py) against an in-memory Firestore."""

import datetime as dt

import pytest

import tenancy
from tests.fixtures.fake_firestore import FakeFirestore

NOW = dt.datetime(2026, 10, 5, 12, tzinfo=dt.UTC)
ANA = {"uid": "u-ana", "email": "ana@example.com", "name": "Ana"}
BEN = {"uid": "u-ben", "email": "ben@example.com", "name": "Ben"}


def register(db, league_id=111, user=ANA, team=1, max_leagues=10, max_per_user=3):
    return tenancy.register(
        db, league_id, 2026, user, team, "Test League", NOW, max_leagues, max_per_user
    )


@pytest.mark.parametrize(
    "text, expected",
    [
        ("12345", 12345),
        (" https://fantasy.espn.com/basketball/league?leagueId=987&seasonId=2026 ", 987),
        ("fantasy.espn.com/basketball/team?leagueId=42&teamId=3", 42),
        ("not a league", None),
        ("", None),
    ],
)
def test_parse_league_id(text, expected):
    assert tenancy.parse_league_id(text) == expected


def test_register_makes_the_registrant_commissioner():
    db = FakeFirestore()
    league = register(db)
    assert league["status"] == "pending" and league["credentials"] == "public"
    assert league["invite_code"]
    [member] = tenancy.memberships(db, ANA["uid"])
    assert member["role"] == "commissioner" and member["team_id"] == 1


def test_a_league_can_only_be_registered_once():
    db = FakeFirestore()
    register(db)
    with pytest.raises(tenancy.TenancyError, match="already on League Lab"):
        register(db, user=BEN)


def test_site_and_per_user_caps():
    db = FakeFirestore()
    register(db, 1, max_leagues=2)
    register(db, 2, max_leagues=2)
    with pytest.raises(tenancy.TenancyError, match="full"):
        register(db, 3, user=BEN, max_leagues=2)
    with pytest.raises(tenancy.TenancyError, match="up to 2"):
        register(db, 3, max_per_user=2)


def test_join_by_invite_and_one_member_per_team():
    db = FakeFirestore()
    code = register(db)["invite_code"]
    league = tenancy.league_by_invite(db, code)
    with pytest.raises(tenancy.TenancyError, match="already claimed"):
        tenancy.join(db, league, BEN, 1, NOW)  # Ana's team
    tenancy.join(db, league, BEN, 2, NOW)
    assert tenancy.claimed_teams(db, 111) == {1: ANA["uid"], 2: BEN["uid"]}
    with pytest.raises(tenancy.TenancyError, match="already in"):
        tenancy.join(db, league, BEN, 3, NOW)


def test_rotating_the_invite_kills_the_old_link():
    db = FakeFirestore()
    old = register(db)["invite_code"]
    new = tenancy.rotate_invite(db, 111)
    assert tenancy.league_by_invite(db, old) is None
    assert tenancy.league_by_invite(db, new)["league_id"] == 111


def test_deleting_hides_the_league_and_frees_the_id():
    db = FakeFirestore()
    code = register(db)["invite_code"]
    tenancy.mark_deleting(db, 111, NOW)
    assert tenancy.get_league(db, 111)["status"] == "deleting"
    assert tenancy.league_by_invite(db, code) is None
    register(db, user=BEN)  # can be registered again while the purge is pending


def test_remove_member_and_set_team():
    db = FakeFirestore()
    register(db)
    tenancy.join(db, tenancy.get_league(db, 111), BEN, 2, NOW)
    with pytest.raises(tenancy.TenancyError):
        tenancy.set_team(db, 111, BEN["uid"], 1)
    tenancy.remove_member(db, 111, BEN["uid"])
    assert [m["uid"] for m in tenancy.members(db, 111)] == [ANA["uid"]]


def test_refresh_is_limited_to_once_an_hour():
    db = FakeFirestore()
    register(db)
    league = tenancy.get_league(db, 111)
    tenancy.claim_refresh(db, league, NOW)
    league = tenancy.get_league(db, 111)
    with pytest.raises(tenancy.TenancyError, match="last hour"):
        tenancy.claim_refresh(db, league, NOW + dt.timedelta(minutes=59))
    tenancy.claim_refresh(db, league, NOW + dt.timedelta(minutes=61))


def test_a_fresh_data_load_also_counts_toward_the_cooldown():
    league = {"last_ingested_at": NOW, "last_refresh_at": NOW - dt.timedelta(hours=5)}
    assert tenancy.refresh_available_at(league) == NOW + dt.timedelta(hours=1)
    assert tenancy.refresh_available_at({}) is None


def test_views_are_recorded_at_most_hourly():
    db = FakeFirestore()
    register(db)
    league = tenancy.get_league(db, 111)  # registered NOW: just seen
    assert not tenancy.record_view(db, league, NOW + dt.timedelta(minutes=30))
    assert tenancy.record_view(db, league, NOW + dt.timedelta(hours=2))
    assert tenancy.get_league(db, 111)["last_viewed_at"] == NOW + dt.timedelta(hours=2)


def test_upsert_user_keeps_created_at():
    db = FakeFirestore()
    tenancy.upsert_user(db, ANA, NOW)
    tenancy.upsert_user(db, ANA, NOW + dt.timedelta(days=1))
    user = db.collection("users").document(ANA["uid"]).get().to_dict()
    assert user["created_at"] == NOW and user["last_seen_at"] == NOW + dt.timedelta(days=1)
