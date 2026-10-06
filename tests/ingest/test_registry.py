"""Which leagues the ingest job refreshes and purges (ingest/registry.py)."""

import datetime as dt

from ingest import registry
from tests.fixtures.fake_firestore import FakeFirestore

NOW = dt.datetime(2026, 10, 20, tzinfo=dt.UTC)


def db_with(**leagues):
    db = FakeFirestore()
    for league_id, doc in leagues.items():
        db.collection("leagues").document(league_id.removeprefix("L")).set(doc)
    return db


def test_only_recently_viewed_leagues_refresh():
    db = db_with(
        L1={"status": "active", "last_viewed_at": NOW - dt.timedelta(days=3)},
        L2={"status": "active", "last_viewed_at": NOW - dt.timedelta(days=30)},
        L3={"status": "pending", "created_at": NOW - dt.timedelta(hours=1)},
        L4={"status": "deleting", "last_viewed_at": NOW},
    )
    assert [lg["league_id"] for lg in registry.leagues_to_refresh(db, NOW)] == [1, 3]


def test_manual_refresh_takes_exactly_the_ids_given_but_never_a_deleting_league():
    db = db_with(
        L2={"status": "active", "last_viewed_at": NOW - dt.timedelta(days=30)},
        L4={"status": "deleting"},
    )
    assert [lg["league_id"] for lg in registry.leagues_to_refresh(db, NOW, {2, 4})] == [2]


def test_task_slices_cover_every_league_once():
    leagues = list(range(10))
    slices = [registry.task_slice(leagues, i, 3) for i in range(3)]
    assert sorted(x for s in slices for x in s) == leagues
    assert registry.task_slice(leagues, 0, 1) == leagues


def test_purge_removes_league_and_members():
    db = db_with(L5={"status": "deleting"}, L6={"status": "active"})
    db.collection("members").document("5__a").set({"league_id": 5, "uid": "a"})
    db.collection("members").document("6__a").set({"league_id": 6, "uid": "a"})
    assert [lg["league_id"] for lg in registry.leagues_to_purge(db)] == [5]
    registry.delete_league(db, 5)
    assert set(db.data["leagues"]) == {"6"}
    assert set(db.data["members"]) == {"6__a"}


def test_success_and_error_are_recorded():
    db = db_with(L7={"status": "pending"})
    registry.record_error(db, 7, "boom" * 200, NOW)
    doc = db.data["leagues"]["7"]
    assert doc["status"] == "error" and len(doc["error"]) == 500
    registry.record_success(db, 7, {"last_ingested_at": NOW})
    doc = db.data["leagues"]["7"]
    assert (doc["status"], doc["error"], doc["last_ingested_at"]) == ("active", None, NOW)


def test_a_league_waiting_for_a_login_is_skipped_until_asked_for():
    db = db_with(L8={"status": "needs_login", "last_viewed_at": NOW})
    assert registry.leagues_to_refresh(db, NOW) == []
    assert [lg["league_id"] for lg in registry.leagues_to_refresh(db, NOW, {8})] == [8]
    registry.record_needs_login(db, 8, "expired", NOW)
    assert db.data["leagues"]["8"]["status"] == "needs_login"
