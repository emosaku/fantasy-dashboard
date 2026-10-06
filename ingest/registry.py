"""The league registry in Firestore -- shared by the ingest job and the dashboard.

Collections (all small documents):
  leagues/{league_id}  -- name, season, status (pending | active | error |
                          needs_login | deleting), credentials ("public",
                          "secret:<name>" for a private league, or "removed"),
                          invite_code, registered_by, created_at, last_viewed_at,
                          last_ingested_at, last_refresh_at, scores_final_through,
                          activity_through_ms, scoring_type, categories, error
  members/{league_id}__{uid} -- league_id, uid, email, name, team_id, role, joined_at
  users/{uid}          -- email, name, created_at, last_seen_at

Ingest reads which leagues to refresh and records progress; it never touches users or
members except when purging a deleted league.
"""

import datetime as dt

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

ACTIVE_DAYS = 14


def client(project: str) -> firestore.Client:
    return firestore.Client(project=project)


def leagues_to_refresh(db, now: dt.datetime, only_ids=None) -> list[dict]:
    """Active leagues someone has opened in the last ACTIVE_DAYS (or registered in
    that time) -- or exactly `only_ids` when given (a manual refresh)."""
    out = []
    for doc in db.collection("leagues").stream():
        league = {"league_id": int(doc.id), **doc.to_dict()}
        if only_ids is not None:
            if league["league_id"] in only_ids and league.get("status") != "deleting":
                out.append(league)
            continue
        if league.get("status") in ("deleting", "needs_login"):
            continue  # a league waiting for a new ESPN login is retried once it has one
        seen = league.get("last_viewed_at") or league.get("created_at")
        if seen and now - seen <= dt.timedelta(days=ACTIVE_DAYS):
            out.append(league)
    return sorted(out, key=lambda league: league["league_id"])


def leagues_to_purge(db) -> list[dict]:
    return [
        {"league_id": int(doc.id), **doc.to_dict()}
        for doc in db.collection("leagues")
        .where(filter=FieldFilter("status", "==", "deleting"))
        .stream()
    ]


def task_slice(leagues: list, task_index: int, task_count: int) -> list:
    """This task's share: every task_count-th league, starting at task_index."""
    return leagues[task_index::task_count] if task_count > 1 else leagues


def record_success(db, league_id: int, fields: dict) -> None:
    db.collection("leagues").document(str(league_id)).set(
        {**fields, "status": "active", "error": None}, merge=True
    )


def record_error(db, league_id: int, message: str, now: dt.datetime) -> None:
    db.collection("leagues").document(str(league_id)).set(
        {"status": "error", "error": message[:500], "last_error_at": now}, merge=True
    )


def record_needs_login(db, league_id: int, message: str, now: dt.datetime) -> None:
    """A private league whose ESPN login is gone or expired: stop refreshing it until
    the commissioner reconnects (the website then sets it back to pending)."""
    db.collection("leagues").document(str(league_id)).set(
        {"status": "needs_login", "error": message[:500], "last_error_at": now}, merge=True
    )


def delete_league(db, league_id: int) -> None:
    """Remove the league and every membership in it."""
    for member in (
        db.collection("members").where(filter=FieldFilter("league_id", "==", league_id)).stream()
    ):
        member.reference.delete()
    db.collection("leagues").document(str(league_id)).delete()
