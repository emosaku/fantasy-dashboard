"""Registering a league: the checks run before it's added.

One ESPN request reads the league's settings and teams. Without a login it only
works for a public league; a private one raises NeedsLogin, and the commissioner can
connect it with their ESPN login (two browser cookies, espn_s2 and SWID). With a
login, the same request must succeed AND the login must belong to someone in the
league: SWID is the ESPN account id, listed as an owner of their team. The league is
refused, with a message for the commissioner, if its format isn't head-to-head
categories or it scores a category League Lab can't compute. Pure Python:
unit-tested with stubbed ESPN responses.
"""

import re  # noqa: I001  (settings must come before the ingest imports)

import settings  # noqa: F401  (puts the repo root on the path for the ingest package)
from ingest.catalog import UnsupportedLeague, league_categories, scoring_type
from ingest.espn_client import LeagueNotAccessible, fetch_views

PRIVATE = (
    "This league is private: ESPN only shares it with a login. You can connect it with "
    "your ESPN login below, or make the league viewable to the public in ESPN (League > "
    "Settings) and try again."
)
REFUSED_LOGIN = (
    "ESPN didn't accept this login for this league. Copy both cookies again from a "
    "browser where you're signed in to ESPN (they change when you sign out)."
)
NOT_IN_LEAGUE = (
    "This ESPN login belongs to an account that isn't in this league. Use the login of "
    "a manager in the league."
)
SWID_PATTERN = re.compile(r"^\{[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}$")


class CannotRegister(Exception):
    """Why this league can't be added; the message is for people."""


class NeedsLogin(CannotRegister):
    """The league is private: it can be added with a manager's ESPN login."""


def clean_cookies(espn_s2: str, swid: str) -> dict:
    """The two cookies as ESPN expects them, from what someone pasted (stray spaces
    and quotes removed, SWID upper-cased with its braces). Raises CannotRegister if they can't be
    ESPN cookies."""
    s2 = (espn_s2 or "").strip().strip("\"'")
    # Kept exactly as the browser stores it (URL-encoded): that's the form ESPN accepts.
    sw = (swid or "").strip().strip("\"'").upper()
    if sw and not sw.startswith("{"):
        sw = "{" + sw + "}"
    if len(s2) < 50 or any(c.isspace() for c in s2):
        raise CannotRegister(
            "That doesn't look like an espn_s2 cookie: it's a long code with no spaces."
        )
    if not SWID_PATTERN.match(sw):
        raise CannotRegister(
            "That doesn't look like a SWID cookie: it looks like "
            "{XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}."
        )
    return {"espn_s2": s2, "SWID": sw}


def team_name(team: dict) -> str:
    name = team.get("name") or f"{team.get('location', '')} {team.get('nickname', '')}"
    return " ".join(name.split()) or f"Team {team.get('id')}"


def preview(league_id: int, season: int, fetch=fetch_views, cookies: dict | None = None) -> dict:
    """{league_name, scoring_type, categories, teams, private, my_team} for a league
    League Lab can add; raises CannotRegister (NeedsLogin for a private league without
    a login) otherwise. my_team is the team the login's owner manages (None without a
    login, or for a league member with no team)."""
    try:
        data = fetch(league_id, season, ["mSettings", "mTeam"], cookies)
    except LeagueNotAccessible as error:
        if "no basketball league" in str(error):
            raise CannotRegister(
                f"ESPN has no basketball league {league_id} in the {season} season. "
                "Check the number in your league's URL (leagueId=...)."
            ) from None
        raise (CannotRegister(REFUSED_LOGIN) if cookies else NeedsLogin(PRIVATE)) from None
    raw = data.get("settings") or {}
    try:
        categories = league_categories(raw.get("scoringSettings") or {})
    except UnsupportedLeague as error:
        raise CannotRegister(str(error)) from None

    my_team = None
    if cookies:
        swid = cookies["SWID"].upper()
        owned = [
            t["id"]
            for t in data.get("teams", [])
            if swid in [o.upper() for o in t.get("owners") or []]
        ]
        members = {(m.get("id") or "").upper() for m in data.get("members", [])}
        if not owned and swid not in members:
            raise CannotRegister(NOT_IN_LEAGUE)
        my_team = int(owned[0]) if owned else None

    teams = sorted(
        ({"team_id": int(t["id"]), "team_name": team_name(t)} for t in data.get("teams", [])),
        key=lambda t: t["team_name"].lower(),
    )
    return {
        "league_name": raw.get("name") or f"League {league_id}",
        "scoring_type": scoring_type(raw["scoringSettings"]),
        "categories": categories,
        "teams": teams,
        "private": cookies is not None,
        "my_team": my_team,
    }
