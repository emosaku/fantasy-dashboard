"""The signed-in person and the league they're looking at -- what every page starts
from (`ctx = league.current()`).

Sign-in is Streamlit's built-in OpenID Connect login with Google (`st.login`; the
client id and secret live in secrets.toml under [auth]). Locally, DEV_AUTH_EMAIL
stands in for it (settings.py; never on Cloud Run).

The league's own rules -- its format (categories or points, locked for the season),
its categories or point values, teams, season length -- come from its Firestore
registry entry, which ingest rewrites on every run. Membership
decides what you can open: only leagues you've registered or joined.
"""

import datetime as dt
from dataclasses import dataclass

import pandas as pd
import streamlit as st
from google.cloud import firestore

import settings
import tenancy
from categories import Category, from_records


@st.cache_resource
def db() -> firestore.Client:
    return firestore.Client(project=settings.PROJECT)


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


# --- Who's signed in ---------------------------------------------------------------


def auth_configured() -> bool:
    try:
        return "client_id" in st.secrets["auth"]
    except (KeyError, FileNotFoundError):
        return False


def current_user() -> dict | None:
    """{uid, email, name} for the signed-in person, else None."""
    if settings.DEV_AUTH_EMAIL:
        email = settings.DEV_AUTH_EMAIL
        return {"uid": f"dev:{email}", "email": email, "name": email.split("@")[0]}
    if not auth_configured() or not st.user.is_logged_in:
        return None
    user = {
        "uid": str(st.user.get("sub")),
        "email": st.user.get("email", ""),
        "name": st.user.get("name") or st.user.get("email", ""),
    }
    if not st.session_state.get("user_recorded"):
        tenancy.upsert_user(db(), user, now())
        st.session_state["user_recorded"] = True
    return user


def sign_in() -> None:
    # No provider name: Streamlit then reads client_id etc. straight from [auth]
    # (st.login("google") would look for an [auth.google] section instead).
    st.login()


def sign_out() -> None:
    st.session_state.clear()
    if not settings.DEV_AUTH_EMAIL:
        st.logout()
    st.rerun()


# --- Leagues -----------------------------------------------------------------------


def my_memberships(force: bool = False) -> list[dict]:
    """This person's member docs, kept for the session (reloaded after any change)."""
    user = current_user()
    if user is None:
        return []
    if force or "memberships" not in st.session_state:
        st.session_state["memberships"] = tenancy.memberships(db(), user["uid"])
    return st.session_state["memberships"]


@st.cache_data(ttl=60, show_spinner=False)
def league_doc(league_id: int) -> dict | None:
    return tenancy.get_league(db(), league_id)


def forget_league_cache() -> None:
    league_doc.clear()
    my_memberships(force=True)


@dataclass(frozen=True)
class Context:
    league_id: int
    name: str
    season: int
    scoring_type: str
    cats: list[Category]
    version: str  # last data load; part of every query's cache key
    team_names: pd.Series  # team_id -> name
    my_team: int | None
    role: str
    current_week: int
    last_week: int
    doc: dict
    format: str = "categories"  # "categories" | "points"
    scoring: tuple = ()  # points leagues: ({stat, points}, ...) in ESPN's order
    lineup_slots: tuple = ()  # points leagues: ((slot, count), ...) starting slots

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
    def scoring_label(self) -> str:
        if self.is_points:
            return "Points"
        return "Each Category" if self.each_category else "Most Categories"


def open_league_ids() -> list[int]:
    """Leagues this person belongs to that still exist (not deleted or deleting)."""
    return [
        m["league_id"]
        for m in my_memberships()
        if (league_doc(m["league_id"]) or {}).get("status", "deleting") != "deleting"
    ]


def switch_to(league_id: int) -> None:
    """Open this league from the next run on. Pages can't set "league_id" directly:
    the sidebar's league picker owns that key once it's drawn."""
    st.session_state["switch_to_league"] = int(league_id)


def selected_league_id() -> int | None:
    ids = open_league_ids()
    if not ids:
        return None
    if st.session_state.get("switch_to_league") in ids:
        st.session_state["league_id"] = st.session_state.pop("switch_to_league")
    chosen = st.session_state.get("league_id")
    if chosen not in ids:
        chosen = ids[0]
        st.session_state["league_id"] = chosen
    return chosen


def league_format(doc: dict | None) -> str:
    """The league's locked format; leagues from before the lock are categories."""
    return (doc or {}).get("format") or "categories"


def build_context(league_id: int) -> Context | None:
    doc = league_doc(league_id)
    if not doc or not doc.get("last_ingested_at"):
        return None
    fmt = league_format(doc)
    if not doc.get("scoring" if fmt == "points" else "categories"):
        return None
    member = next((m for m in my_memberships() if m["league_id"] == league_id), {})
    teams = pd.Series(
        {int(t["team_id"]): str(t["team_name"]).strip() for t in doc.get("teams", [])}
    ).sort_values()
    return Context(
        league_id=league_id,
        name=doc.get("league_name") or f"League {league_id}",
        season=int(doc["season"]),
        scoring_type=doc.get("scoring_type", "H2H_MOST_CATEGORIES"),
        cats=from_records(doc.get("categories") or []),
        version=doc["last_ingested_at"].isoformat(),
        team_names=teams,
        my_team=member.get("team_id"),
        role=member.get("role", "member"),
        current_week=int(doc.get("current_matchup_period") or 1),
        last_week=int(
            doc.get("reg_season_matchup_periods") or doc.get("current_matchup_period") or 1
        ),
        doc=doc,
        format=fmt,
        scoring=tuple(doc.get("scoring") or ()),
        lineup_slots=tuple((doc.get("lineup_slots") or {}).items()),
    )


def current() -> Context:
    """The league this page shows; stops the page with a note if there isn't one."""
    league_id = selected_league_id()
    if league_id is None:
        st.info(
            "You're not in a league yet. Register one, or open your commissioner's invite link."
        )
        st.page_link("views/register.py", label="Register a league", icon=":material/add:")
        st.page_link(
            "views/draft.py", icon=":material/format_list_numbered:",
            label="Or run a mock draft: the Draft page works any time, no league needed",
        )  # fmt: skip
        st.stop()
    ctx = build_context(league_id)
    if ctx is None:
        doc = league_doc(league_id) or {}
        if doc.get("status") == "error":
            st.error(f"Loading this league failed: {doc.get('error') or 'unknown error'}")
        else:
            st.info(
                "This league's data is loading for the first time -- it takes a few "
                "minutes. Reload the page shortly."
            )
        st.stop()
    if ctx.doc.get("status") == "needs_login":
        who = (
            "Reconnect it on League settings."
            if ctx.is_commissioner
            else ("The commissioner can reconnect it.")
        )
        st.warning(
            f"This league's data isn't refreshing: its ESPN login expired or was removed. {who}"
        )
    if ctx.doc.get("format_mismatch"):
        st.warning(
            f"ESPN now says this league plays {ctx.doc['format_mismatch']}, but League Lab "
            f"runs its {ctx.format} tools for the {ctx.season - 1}-{str(ctx.season)[2:]} "
            "season, as confirmed at sign-up. Its data isn't refreshing until the site owner "
            "reloads it in the right format."
        )
    if tenancy.record_view(db(), ctx.doc, now()):
        league_doc.clear()
    return ctx
