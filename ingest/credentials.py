"""ESPN cookies for a private league (Phase 2).

A league document's `credentials` is:
  * "public"         -- no cookies needed;
  * "secret:<name>"  -- a Secret Manager secret in this project holding
                        {"espn_s2": ..., "SWID": ...}, written by the website when the
                        commissioner connected the league. Only the ingest job's
                        account can read it; the website can write but not read it;
  * "removed"        -- the commissioner disconnected the login.
A missing or removed login raises NeedsLogin, so the league waits for its
commissioner to reconnect instead of failing every day.
"""

import base64
import json

import google.auth
from google.auth.transport.requests import AuthorizedSession

SECRETS_API = "https://secretmanager.googleapis.com/v1"


class NeedsLogin(Exception):
    """The league's ESPN login is missing, removed or no longer accepted; the
    message is for people."""


EXPIRED = (
    "ESPN no longer accepts this league's saved login (ESPN logins expire). The "
    "commissioner can reconnect it on the League settings page."
)
REMOVED = "The commissioner removed this league's ESPN login, so its data isn't refreshed."


def cookies_for(league: dict, project: str, session=None) -> dict | None:
    source = league.get("credentials") or "public"
    if source == "public":
        return None
    if source == "removed":
        raise NeedsLogin(REMOVED)
    if not source.startswith("secret:"):
        raise ValueError(f"Unknown credentials source: {source!r}")
    name = source.removeprefix("secret:")
    if session is None:
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        session = AuthorizedSession(creds)
    url = f"{SECRETS_API}/projects/{project}/secrets/{name}/versions/latest:access"
    response = session.get(url)
    if response.status_code == 404:
        raise NeedsLogin(REMOVED)
    response.raise_for_status()
    return json.loads(base64.b64decode(response.json()["payload"]["data"]))
