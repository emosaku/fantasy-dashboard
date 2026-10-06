"""Who belongs to which league -- the Firestore side of League Lab (the registry the
ingest job reads, plus users and memberships). See ingest/registry.py for the
collections. No Streamlit here: every function takes the Firestore client, so the
tests run against an in-memory fake.

Rules:
  * Anyone signed in can register a public league, up to MAX_LEAGUES on the site and
    MAX_LEAGUES_PER_USER each. The person who registers it is its commissioner.
  * Others join only through the league's invite link, and claim a team. A team has
    one member; the commissioner can remove members and rotate the invite link.
  * The commissioner can delete the league: it's marked "deleting" and the ingest
    job removes every row, registry entry and stored credential.
  * A league's data can be refreshed on demand at most once an hour.
"""

import datetime as dt
import re
import secrets

from google.cloud.firestore_v1.base_query import FieldFilter

REFRESH_COOLDOWN = dt.timedelta(hours=1)
VIEW_EVERY = dt.timedelta(hours=1)  # how often an open league records last_viewed_at


class TenancyError(Exception):
    """A request that breaks a rule above; the message is for people."""


def parse_league_id(text: str) -> int | None:
    """A league id from what someone pasted: the number, or any ESPN league URL
    (`...?leagueId=12345...`)."""
    text = (text or "").strip()
    found = re.search(r"leagueId=(\d+)", text)
    if found:
        return int(found.group(1))
    return int(text) if text.isdigit() else None


def new_invite_code() -> str:
    return secrets.token_urlsafe(9)


def _member_id(league_id: int, uid: str) -> str:
    return f"{league_id}__{uid}"


def _league_ref(db, league_id: int):
    return db.collection("leagues").document(str(league_id))


def upsert_user(db, user: dict, now: dt.datetime) -> None:
    ref = db.collection("users").document(user["uid"])
    fields = {"email": user["email"], "name": user["name"], "last_seen_at": now}
    if not ref.get().exists:
        fields["created_at"] = now
    ref.set(fields, merge=True)


def get_league(db, league_id: int) -> dict | None:
    snap = _league_ref(db, league_id).get()
    return {"league_id": int(league_id), **snap.to_dict()} if snap.exists else None


def league_by_invite(db, code: str) -> dict | None:
    if not code:
        return None
    for snap in (
        db.collection("leagues").where(filter=FieldFilter("invite_code", "==", code)).stream()
    ):
        league = {"league_id": int(snap.id), **snap.to_dict()}
        if league.get("status") != "deleting":
            return league
    return None


def memberships(db, uid: str) -> list[dict]:
    """This person's leagues: member docs (league_id, team_id, role ...)."""
    return [
        snap.to_dict()
        for snap in db.collection("members").where(filter=FieldFilter("uid", "==", uid)).stream()
    ]


def members(db, league_id: int) -> list[dict]:
    return [
        snap.to_dict()
        for snap in db.collection("members")
        .where(filter=FieldFilter("league_id", "==", int(league_id)))
        .stream()
    ]


def claimed_teams(db, league_id: int) -> dict[int, str]:
    """team_id -> uid of the member who claimed it."""
    return {m["team_id"]: m["uid"] for m in members(db, league_id) if m.get("team_id") is not None}


def _live_leagues(db) -> list[dict]:
    return [
        snap.to_dict() | {"league_id": int(snap.id)}
        for snap in db.collection("leagues").stream()
        if (snap.to_dict() or {}).get("status") != "deleting"
    ]


def register(
    db,
    league_id: int,
    season: int,
    user: dict,
    team_id: int | None,
    league_name: str,
    now: dt.datetime,
    max_leagues: int,
    max_per_user: int,
) -> dict:
    """Add a public league with `user` as commissioner. Returns the league doc."""
    existing = get_league(db, league_id)
    if existing and existing.get("status") != "deleting":
        raise TenancyError(
            "This league is already on League Lab. Ask its commissioner for the invite link."
        )
    live = _live_leagues(db)
    if len(live) >= max_leagues:
        raise TenancyError(
            "League Lab is full for now: it's taking a small number of leagues while "
            "it's tested. Try again later."
        )
    if sum(lg.get("registered_by") == user["uid"] for lg in live) >= max_per_user:
        raise TenancyError(f"You can register up to {max_per_user} leagues.")

    league = {
        "season": int(season),
        "league_name": league_name,
        "status": "pending",  # until the first data load finishes
        "credentials": "public",
        "invite_code": new_invite_code(),
        "registered_by": user["uid"],
        "created_at": now,
        "last_viewed_at": now,
        "internal_test": False,
    }
    _league_ref(db, league_id).set(league)
    _add_member(db, league_id, user, team_id, "commissioner", now)
    return {"league_id": int(league_id), **league}


def _add_member(db, league_id: int, user: dict, team_id, role: str, now) -> None:
    db.collection("members").document(_member_id(league_id, user["uid"])).set(
        {
            "league_id": int(league_id),
            "uid": user["uid"],
            "email": user["email"],
            "name": user["name"],
            "team_id": None if team_id is None else int(team_id),
            "role": role,
            "joined_at": now,
        }
    )


def join(db, league: dict, user: dict, team_id: int | None, now: dt.datetime) -> None:
    """Join through an invite: claim a team nobody else has."""
    league_id = league["league_id"]
    mine = db.collection("members").document(_member_id(league_id, user["uid"])).get()
    if mine.exists:
        raise TenancyError("You're already in this league.")
    if team_id is not None:
        owner = claimed_teams(db, league_id).get(int(team_id))
        if owner and owner != user["uid"]:
            raise TenancyError(
                "Someone has already claimed that team. If it's yours, ask the "
                "commissioner to remove them."
            )
    _add_member(db, league_id, user, team_id, "member", now)


def set_team(db, league_id: int, uid: str, team_id: int | None) -> None:
    owner = claimed_teams(db, league_id).get(team_id) if team_id is not None else None
    if owner and owner != uid:
        raise TenancyError("Someone has already claimed that team.")
    db.collection("members").document(_member_id(league_id, uid)).set(
        {"team_id": team_id}, merge=True
    )


def remove_member(db, league_id: int, uid: str) -> None:
    db.collection("members").document(_member_id(league_id, uid)).delete()


def rotate_invite(db, league_id: int) -> str:
    code = new_invite_code()
    _league_ref(db, league_id).set({"invite_code": code}, merge=True)
    return code


def mark_deleting(db, league_id: int, now: dt.datetime) -> None:
    """Hide the league at once; the ingest job purges it (and its members) next run."""
    _league_ref(db, league_id).set(
        {"status": "deleting", "invite_code": None, "delete_requested_at": now}, merge=True
    )


def record_view(db, league: dict, now: dt.datetime) -> bool:
    """Keep the league on the daily refresh: stamp last_viewed_at, at most hourly."""
    seen = league.get("last_viewed_at")
    if seen and now - seen < VIEW_EVERY:
        return False
    _league_ref(db, league["league_id"]).set({"last_viewed_at": now}, merge=True)
    return True


def refresh_available_at(league: dict) -> dt.datetime | None:
    """When an on-demand refresh is next allowed (None = now): an hour after the
    last refresh or data load, whichever is later."""
    stamps = [league.get("last_refresh_at"), league.get("last_ingested_at")]
    latest = max((s for s in stamps if s), default=None)
    return latest + REFRESH_COOLDOWN if latest else None


def claim_refresh(db, league: dict, now: dt.datetime) -> None:
    """Record an on-demand refresh, or raise if one ran within the last hour."""
    ready = refresh_available_at(league)
    if ready and now < ready:
        raise TenancyError("This league was refreshed in the last hour. Try again later.")
    _league_ref(db, league["league_id"]).set({"last_refresh_at": now}, merge=True)
