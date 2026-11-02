"""Per-request context: who's signing in (auth.py) and the league they asked for.

Every /api/leagues/{id}/... endpoint goes through `league_context`, which refuses a
league the person doesn't belong to (403), one that doesn't exist or is being
deleted (404), and one whose first data load hasn't landed yet (409). Membership is
the same Firestore `members` collection the Streamlit app uses (app/tenancy.py).
"""

import datetime as dt
from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, Request

from api.auth import NotSignedIn, User, bearer
from categories import Category, from_records


@dataclass
class LeagueContext:
    league_id: int
    name: str
    season: int
    format: str  # "categories" | "points"
    scoring_type: str
    version: str  # the last data load: part of every cache key
    teams: dict  # team_id -> name
    my_team: int | None
    role: str
    current_week: int
    last_week: int
    doc: dict = field(repr=False)
    cats: list[Category] = field(default_factory=list)
    scoring: list = field(default_factory=list)
    lineup_slots: dict = field(default_factory=dict)

    @property
    def is_points(self) -> bool:
        return self.format == "points"

    @property
    def each_category(self) -> bool:
        return self.scoring_type == "H2H_EACH_CATEGORY"

    @property
    def is_commissioner(self) -> bool:
        return self.role == "commissioner"

    @property
    def bench(self) -> int:
        return int(self.doc.get("bench_slots") or 0)

    @property
    def data_as_of(self) -> dt.datetime | None:
        return self.doc.get("last_ingested_at")

    def team_for(self, team: int | None) -> int:
        """The team a request is about: `team`, else the person's own. Only the
        commissioner may look at another team's recommendations, as in the app."""
        chosen = self.my_team if team is None else int(team)
        if chosen is None:
            raise HTTPException(409, "Pick your team in this league first.")
        if chosen != self.my_team and not self.is_commissioner:
            raise HTTPException(403, "Recommendations are for your own team.")
        if chosen not in self.teams:
            raise HTTPException(404, "No such team in this league.")
        return chosen


def store(request: Request):
    return request.app.state.store


def current_user(request: Request) -> User:
    verifier = request.app.state.verifier
    if verifier is None:
        raise HTTPException(503, "Sign-in isn't configured on this server.")
    header = request.headers.get("authorization")
    try:
        if getattr(verifier, "dev", False):
            return verifier.verify(header or "")
        return verifier.verify(bearer(header))
    except NotSignedIn as error:
        raise HTTPException(401, str(error)) from None


def build(doc: dict, member: dict) -> LeagueContext:
    fmt = doc.get("format") or "categories"
    return LeagueContext(
        league_id=int(doc["league_id"]),
        name=doc.get("league_name") or f"League {doc['league_id']}",
        season=int(doc.get("season") or 0),
        format=fmt,
        scoring_type=doc.get("scoring_type") or "H2H_MOST_CATEGORIES",
        version=doc["last_ingested_at"].isoformat(),
        teams={int(t["team_id"]): str(t["team_name"]).strip() for t in doc.get("teams", [])},
        my_team=None if member.get("team_id") is None else int(member["team_id"]),
        role=member.get("role", "member"),
        current_week=int(doc.get("current_matchup_period") or 1),
        last_week=int(
            doc.get("reg_season_matchup_periods") or doc.get("current_matchup_period") or 1
        ),  # fmt: skip
        doc=doc,
        cats=from_records(doc.get("categories") or []),
        scoring=list(doc.get("scoring") or []),
        lineup_slots=dict(doc.get("lineup_slots") or {}),
    )


def membership(league_id: int, user: User, store) -> dict:
    for m in store.memberships(user.uid):
        if int(m["league_id"]) == int(league_id):
            return m
    raise HTTPException(403, "You're not a member of this league.")


def league_context(league_id: int, user: User = Depends(current_user),
                   store=Depends(store)) -> LeagueContext:  # fmt: skip
    member = membership(league_id, user, store)
    doc = store.league(league_id)
    if not doc or doc.get("status") == "deleting":
        raise HTTPException(404, "This league isn't on League Lab.")
    if not doc.get("last_ingested_at"):
        raise HTTPException(409, "This league's first data load hasn't finished yet.")
    return build(doc, member)
