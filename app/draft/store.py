"""Your drafts in Firestore (`drafts/u-{uid}-{setup}-{mode}`): saved as you go, so a
draft can be left and picked up later, on any device you're signed in on. Each person's
drafts are their own; one per setup and mode (bots picking, or you entering every
pick). No Streamlit here: every function takes the Firestore client, so tests run on
the in-memory fake.
"""

import datetime as dt

from draft.state import Draft

MODES = ("bots", "entered")


def doc_id(uid: str, setup, mode: str) -> str:
    return f"u-{uid}-{setup.key}-{mode}"


def load(db, draft_id: str) -> Draft | None:
    snap = db.collection("drafts").document(draft_id).get()
    return Draft.from_dict(snap.to_dict()) if snap.exists else None


def save(db, draft_id: str, draft: Draft, uid: str, now: dt.datetime) -> None:
    db.collection("drafts").document(draft_id).set(
        {**draft.to_dict(), "owner": uid, "updated_at": now}
    )


def clear(db, draft_id: str) -> None:
    db.collection("drafts").document(draft_id).delete()
