"""Who am I, my leagues, and adding a league (onboarding)."""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import onboarding
import tenancy
from api.auth import User
from api.context import current_user, store

router = APIRouter()


def _league_row(store, member: dict) -> dict | None:
    doc = store.league(member["league_id"])
    if not doc or doc.get("status") == "deleting":
        return None
    ingested = doc.get("last_ingested_at")
    return {
        "league_id": int(member["league_id"]),
        "name": doc.get("league_name") or f"League {member['league_id']}",
        "format": doc.get("format") or "categories",
        "season": doc.get("season"),
        "team_id": member.get("team_id"),
        "role": member.get("role", "member"),
        "status": doc.get("status"),
        "data_as_of": ingested.isoformat() if ingested else None,
    }


def my_leagues(store, user: User) -> list[dict]:
    rows = [_league_row(store, m) for m in store.memberships(user.uid)]
    return sorted((r for r in rows if r), key=lambda r: r["name"].lower())


@router.get("/me")
def me(user: User = Depends(current_user), store=Depends(store)):
    """The signed-in person and their leagues. Records the visit (tenancy.upsert_user)
    so the user exists for Firestore lookups, as the Streamlit sign-in does."""
    store.upsert_user({"uid": user.uid, "email": user.email, "name": user.name},
                      dt.datetime.now(dt.UTC))  # fmt: skip
    return {
        "user": {"uid": user.uid, "email": user.email, "name": user.name},
        "leagues": my_leagues(store, user),
        "subscription": None,  # Phase 9 (Whop backlog R11, R12)
    }


@router.get("/leagues")
def leagues(user: User = Depends(current_user), store=Depends(store)):
    return my_leagues(store, user)


class PreviewIn(BaseModel):
    league: str  # a league id or ESPN league URL


class RegisterIn(BaseModel):
    league: str
    team_id: int | None = None


def _league_id(text: str) -> int:
    league_id = tenancy.parse_league_id(text)
    if league_id is None:
        raise HTTPException(422, "That isn't an ESPN league id or link.")
    return league_id


@router.post("/onboarding/preview")
def preview(body: PreviewIn, user: User = Depends(current_user), store=Depends(store)):
    """Today's Register-page check (onboarding.preview): format, categories or point
    values, scored stats we can't count, teams. Public leagues only at launch."""
    league_id = _league_id(body.league)
    try:
        found = store.preview(league_id)
    except onboarding.CannotRegister as error:
        raise HTTPException(422, str(error)) from None
    return {"league_id": league_id, **found}


@router.post("/onboarding/register-league", status_code=201)
def register(body: RegisterIn, user: User = Depends(current_user), store=Depends(store)):
    """Register a public league with the caller as commissioner and start its first
    data load. Its pages answer 409 until that load lands."""
    league_id = _league_id(body.league)
    try:
        found = store.preview(league_id)
    except onboarding.CannotRegister as error:
        raise HTTPException(422, str(error)) from None
    if body.team_id is not None and body.team_id not in {t["team_id"] for t in found["teams"]}:
        raise HTTPException(422, "That team isn't in this league.")
    person = {"uid": user.uid, "email": user.email, "name": user.name}
    try:
        doc = store.register(league_id, person, body.team_id, found, dt.datetime.now(dt.UTC))
    except tenancy.TenancyError as error:
        raise HTTPException(409, str(error)) from None
    return {"league_id": league_id, "name": doc["league_name"], "status": doc["status"]}
