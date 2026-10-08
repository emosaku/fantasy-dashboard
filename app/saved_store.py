"""Where saved trades live on the main site: one BigQuery table, `saved_trades`
(sql/ddl/saved_trades.sql), a row per person, team and trade. The trade itself is a
JSON record (saved_trades.SavedTrade), so the table never changes shape. The dashboard
may write this one table and no other.
"""

import datetime as dt
import json

from google.cloud import bigquery

from queries import DATASET, PROJECT, _client
from saved_trades import SavedTrade

TABLE = f"`{PROJECT}.{DATASET}.saved_trades`"


def to_record(trade: SavedTrade) -> str:
    """The trade as JSON, without its timestamp (that's its own column)."""
    data = trade.to_dict()
    data.pop("saved_at", None)
    return json.dumps(data, sort_keys=True)


def from_record(record: str, saved_at: dt.datetime | None) -> SavedTrade:
    return SavedTrade.from_dict({**json.loads(record), "saved_at": saved_at})


def _run(sql: str, **params) -> bigquery.table.RowIterator:
    kinds = {int: "INT64", str: "STRING", dt.datetime: "TIMESTAMP"}
    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(name, kinds[type(value)], value)
            for name, value in params.items()
        ]
    )
    return _client().query(sql, job_config=config).result()


def load(username: str, team_id: int) -> list[SavedTrade]:
    rows = _run(
        f"SELECT record, saved_at FROM {TABLE} WHERE username = @user AND team_id = @team",
        user=username, team=int(team_id),
    )  # fmt: skip
    return [from_record(r.record, r.saved_at) for r in rows]


def save(username: str, trade: SavedTrade) -> None:
    """Saving the same move again replaces it (same trade id)."""
    _run(
        f"MERGE {TABLE} AS t USING (SELECT @user AS username, @team AS team_id, @id AS "
        "trade_id, @record AS record, @saved_at AS saved_at) AS s "
        "ON t.username = s.username AND t.trade_id = s.trade_id "
        "WHEN MATCHED THEN UPDATE SET team_id = s.team_id, record = s.record, "
        "saved_at = s.saved_at WHEN NOT MATCHED THEN INSERT ROW",
        user=username, team=int(trade.team_id), id=trade.id, record=to_record(trade),
        saved_at=trade.saved_at or dt.datetime.now(dt.UTC),
    )  # fmt: skip


def delete(username: str, trade_id: str) -> None:
    _run(f"DELETE FROM {TABLE} WHERE username = @user AND trade_id = @id",
         user=username, id=trade_id)  # fmt: skip
