"""Warm the trade finder cache after the morning refresh: every team of every loaded
league gets its default search (default stat window and swing size, no tier
overrides) computed once and stored, so nobody waits for it on the Trades page.

Run as a Cloud Run Job from the API's image after `league-ingest` (or by hand):

    GCP_PROJECT_ID=league-lab-whop python -m api.precompute
    GCP_PROJECT_ID=league-lab-whop LEAGUE_IDS=403104643 python -m api.precompute

A league that fails is reported and skipped; the API computes its search on demand.
"""

import datetime as dt
import os
import sys

from api.context import build
from api.services import LeagueData
from api.store import Store, from_env

SKIP = {"deleting", "pending"}


def leagues(db, only=None) -> list[dict]:
    out = []
    for snap in db.collection("leagues").stream():
        doc = {"league_id": int(snap.id), **(snap.to_dict() or {})}
        if doc.get("status") in SKIP or not doc.get("last_ingested_at"):
            continue
        if only and doc["league_id"] not in only:
            continue
        out.append(doc)
    return out


def warm(store: Store, doc: dict, now) -> int:
    """Every team's default finder search for one league; returns teams done."""
    ctx = build(doc, {"team_id": None, "role": "commissioner"})
    data = LeagueData(store, ctx)
    window = data.window(None)
    for team in ctx.teams:
        data.finder(team, window, now=now)
    return len(ctx.teams)


def main(env=os.environ) -> int:
    store = from_env(env)
    only = {int(i) for i in env.get("LEAGUE_IDS", "").split(",") if i.strip()}
    now = dt.datetime.now(dt.UTC)
    failed = 0
    for doc in leagues(store.db, only or None):
        try:
            print(f"league {doc['league_id']}: {warm(store, doc, now)} teams")
        except Exception as error:  # one league mustn't stop the rest
            failed += 1
            print(f"league {doc['league_id']}: FAILED: {error}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
