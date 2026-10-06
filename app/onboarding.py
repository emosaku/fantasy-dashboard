"""Registering a league: the checks run before it's added.

One ESPN request with no login (so it only works for a public league) reads the
league's settings and teams. The league is refused, with a message for the
commissioner, if ESPN won't share it, if its format isn't head-to-head categories,
or if it scores a category League Lab can't compute. Pure Python: unit-tested with
a stubbed ESPN response.
"""

from ingest.catalog import UnsupportedLeague, league_categories
from ingest.espn_client import LeagueNotAccessible, fetch_views

import settings  # noqa: F401  (puts the repo root on the path for the ingest package)

PRIVATE = (
    "ESPN won't share this league without a login, so it's private. League Lab supports "
    "public leagues for now: in ESPN, the commissioner can open League > Settings and "
    "make the league viewable to the public, then try again."
)


class CannotRegister(Exception):
    """Why this league can't be added; the message is for people."""


def team_name(team: dict) -> str:
    name = team.get("name") or f"{team.get('location', '')} {team.get('nickname', '')}"
    return " ".join(name.split()) or f"Team {team.get('id')}"


def preview(league_id: int, season: int, fetch=fetch_views) -> dict:
    """{league_name, scoring_type, categories, teams} for a public, supported league;
    raises CannotRegister otherwise."""
    try:
        data = fetch(league_id, season, ["mSettings", "mTeam"])
    except LeagueNotAccessible as error:
        if "no basketball league" in str(error):
            raise CannotRegister(
                f"ESPN has no basketball league {league_id} in the {season} season. "
                "Check the number in your league's URL (leagueId=...)."
            ) from None
        raise CannotRegister(PRIVATE) from None
    raw = data.get("settings") or {}
    try:
        categories = league_categories(raw.get("scoringSettings") or {})
    except UnsupportedLeague as error:
        raise CannotRegister(str(error)) from None
    teams = sorted(
        ({"team_id": int(t["id"]), "team_name": team_name(t)} for t in data.get("teams", [])),
        key=lambda t: t["team_name"].lower(),
    )
    return {
        "league_name": raw.get("name") or f"League {league_id}",
        "scoring_type": raw["scoringSettings"]["scoringType"],
        "categories": categories,
        "teams": teams,
    }
