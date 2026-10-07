"""A live draft's picks in Firestore (drafts/{league}-{season}), so the Draft page can
be open on a phone and a laptop at once and a refresh loses nothing. No Streamlit
here: every function takes the Firestore client, so tests run on the in-memory fake.
One person enters picks at a time; the last write wins."""

import datetime as dt

from draft.state import Draft


def doc_id(league_id: int, season: int) -> str:
    return f"{int(league_id)}-{int(season)}"


def load(db, league_id: int, season: int) -> Draft | None:
    snap = db.collection("drafts").document(doc_id(league_id, season)).get()
    return Draft.from_dict(snap.to_dict()) if snap.exists else None


def save(db, league_id: int, season: int, draft: Draft, uid: str, now: dt.datetime) -> None:
    db.collection("drafts").document(doc_id(league_id, season)).set(
        {
            **draft.to_dict(),
            "league_id": int(league_id),
            "season": int(season),
            "updated_at": now,
            "updated_by": uid,
        }  # fmt: skip
    )


def clear(db, league_id: int, season: int) -> None:
    db.collection("drafts").document(doc_id(league_id, season)).delete()
