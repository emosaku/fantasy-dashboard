"""ESPN cookies for a league that has them (Phase 2: private leagues).

A league document's `credentials` is "public" (no cookies -- every Phase 1 league) or
"secret:<name>": a Secret Manager secret in this project holding
{"espn_s2": ..., "SWID": ...}. Only the ingest job's account can read those secrets.
"""

import base64
import json

import google.auth
from google.auth.transport.requests import AuthorizedSession

SECRETS_API = "https://secretmanager.googleapis.com/v1"


def cookies_for(league: dict, project: str, session=None) -> dict | None:
    source = league.get("credentials") or "public"
    if source == "public":
        return None
    if not source.startswith("secret:"):
        raise ValueError(f"Unknown credentials source: {source!r}")
    name = source.removeprefix("secret:")
    if session is None:
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        session = AuthorizedSession(creds)
    url = f"{SECRETS_API}/projects/{project}/secrets/{name}/versions/latest:access"
    response = session.get(url)
    response.raise_for_status()
    return json.loads(base64.b64decode(response.json()["payload"]["data"]))
