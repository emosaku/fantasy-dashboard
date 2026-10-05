"""The MERGE statement merge_load sends -- built as a string, so it's testable
without BigQuery."""

import datetime as dt

from ingest.bigquery_load import build_merge_sql

COLUMNS = ["season", "snapshot_date", "team_id", "player_id", "player_name"]
KEYS = ["season", "snapshot_date", "team_id", "player_id"]


def test_plain_merge_never_deletes():
    sql = build_merge_sql("p.d.rosters", "p.d.rosters_staging", COLUMNS, KEYS)
    assert "DELETE" not in sql
    assert "UPDATE SET T.player_name = S.player_name" in sql


def test_scoped_merge_deletes_only_inside_the_snapshot():
    scope = {"season": 2027, "snapshot_date": dt.date(2026, 10, 5)}
    sql = build_merge_sql("p.d.rosters", "p.d.rosters_staging", COLUMNS, KEYS, scope)
    assert (
        "WHEN NOT MATCHED BY SOURCE AND T.season = 2027 "
        "AND T.snapshot_date = DATE '2026-10-05' THEN DELETE"
    ) in sql
