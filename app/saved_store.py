"""Where saved trades live on League Lab: Firestore, `saved_trades/{league}-{uid}-{id}`,
one document per trade, each person's own. Deleted with the league
(ingest/registry.py). No Streamlit here: every function takes the Firestore client, so
tests run on the in-memory fake."""

from google.cloud.firestore_v1.base_query import FieldFilter

from saved_trades import SavedTrade


def _doc(db, league_id: int, uid: str, trade_id: str):
    return db.collection("saved_trades").document(f"{int(league_id)}-{uid}-{trade_id}")


def load(db, league_id: int, uid: str, team_id: int) -> list[SavedTrade]:
    """This person's saved trades for one team of one league."""
    query = (
        db.collection("saved_trades")
        .where(filter=FieldFilter("league_id", "==", int(league_id)))
        .where(filter=FieldFilter("uid", "==", uid))
        .where(filter=FieldFilter("team_id", "==", int(team_id)))
    )
    return [SavedTrade.from_dict(snap.to_dict()) for snap in query.stream()]


def save(db, league_id: int, uid: str, trade: SavedTrade) -> None:
    _doc(db, league_id, uid, trade.id).set(
        {**trade.to_dict(), "league_id": int(league_id), "uid": uid}
    )


def delete(db, league_id: int, uid: str, trade_id: str) -> None:
    _doc(db, league_id, uid, trade_id).delete()
