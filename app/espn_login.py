"""Saving and removing a private league's ESPN login (its espn_s2 and SWID cookies).

The website can WRITE a league's login but never READ it back: its account has a
custom role (leagueSecretWriter) to create secrets named league-*, add versions,
destroy old ones and delete them -- but not to access any secret's value. Only the
ingest job can read the login. Each league has one secret, `league-<id>-espn`;
saving a new login adds a version and destroys the old ones, so a replaced login
can't be read by anyone.

The cookies pass through the website's memory once, while they're checked against
ESPN and saved. They're never logged, cached or written anywhere else.
"""

import json

from google.api_core.exceptions import AlreadyExists, NotFound

ENABLED = 1  # SecretVersion.State.ENABLED


def secret_id(league_id: int) -> str:
    return f"league-{int(league_id)}-espn"


def save(client, project: str, league_id: int, cookies: dict) -> str:
    """Store the login; returns the league's `credentials` value."""
    parent = f"projects/{project}"
    sid = secret_id(league_id)
    name = f"{parent}/secrets/{sid}"
    try:
        client.create_secret(
            request={
                "parent": parent,
                "secret_id": sid,
                "secret": {
                    "replication": {"automatic": {}},
                    "labels": {"app": "league-lab", "league_id": str(int(league_id))},
                },
            }
        )
    except AlreadyExists:
        pass
    payload = json.dumps({"espn_s2": cookies["espn_s2"], "SWID": cookies["SWID"]}).encode()
    new = client.add_secret_version(request={"parent": name, "payload": {"data": payload}})
    for version in client.list_secret_versions(request={"parent": name}):
        if version.name != new.name and int(version.state) == ENABLED:
            client.destroy_secret_version(request={"name": version.name})
    return f"secret:{sid}"


def remove(client, project: str, league_id: int) -> None:
    """Delete the league's stored login (every version). Missing is fine."""
    try:
        client.delete_secret(request={"name": f"projects/{project}/secrets/{secret_id(league_id)}"})
    except NotFound:
        pass


def client():
    from google.cloud import secretmanager

    return secretmanager.SecretManagerServiceClient()
