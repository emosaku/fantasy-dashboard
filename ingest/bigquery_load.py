"""Idempotent load: stage the DataFrame, then MERGE into the target table.

Every table follows the same pattern (sql/ddl/*.sql documents each table's natural
key) so re-running ingest -- intentionally, or because Cloud Scheduler fires twice --
never duplicates rows.

Daily-snapshot tables (rosters, player_stats, ...) also pass a `scope`: the run is
the complete picture for that snapshot_date, so rows in it that this run no longer
has are deleted. Without that, a player dropped between two same-day runs kept his
old roster row for the rest of the day.
"""

import datetime as dt

import pandas as pd
from google.cloud import bigquery


def _sql_literal(value) -> str:
    if isinstance(value, dt.date):
        return f"DATE '{value.isoformat()}'"
    if isinstance(value, int):
        return str(value)
    raise TypeError(f"unsupported scope value: {value!r}")


def build_merge_sql(
    target_table: str,
    staging_table: str,
    columns: list[str],
    key_columns: list[str],
    scope: dict | None = None,
) -> str:
    non_key_columns = [c for c in columns if c not in key_columns]
    on_clause = " AND ".join(f"T.{c} = S.{c}" for c in key_columns)
    update_clause = ", ".join(f"T.{c} = S.{c}" for c in non_key_columns)
    all_columns = ", ".join(columns)
    insert_values = ", ".join(f"S.{c}" for c in columns)
    delete_clause = ""
    if scope:
        condition = " AND ".join(f"T.{c} = {_sql_literal(v)}" for c, v in scope.items())
        delete_clause = f"\n    WHEN NOT MATCHED BY SOURCE AND {condition} THEN DELETE"
    return f"""
    MERGE `{target_table}` T
    USING `{staging_table}` S
    ON {on_clause}
    WHEN MATCHED THEN UPDATE SET {update_clause}
    WHEN NOT MATCHED THEN INSERT ({all_columns}) VALUES ({insert_values}){delete_clause}
    """


def merge_load(
    client: bigquery.Client,
    project: str,
    dataset: str,
    table: str,
    df: pd.DataFrame,
    key_columns: list[str],
    scope: dict | None = None,
) -> None:
    """scope: e.g. {"season": 2027, "snapshot_date": date} -- target rows matching it
    but missing from df are deleted. Never applied when df is empty, so a failed or
    empty pull can't wipe a day's data."""
    if df.empty:
        print(f"{table}: nothing to load")
        return

    staging_table = f"{project}.{dataset}.{table}_staging"
    target_table = f"{project}.{dataset}.{table}"

    # Schema is pinned to the target table's, not autodetected: a column that's all
    # NULL in this run's DataFrame (e.g. transactions.player_id, which espn-api never
    # actually populates) has no non-null value for autodetect to infer a type from,
    # and it has guessed STRING where the target column is INT64 -- a MERGE type
    # mismatch. Autodetection also isn't stable across pandas-gbq versions/presence,
    # which is exactly how this surfaced: fine with pandas-gbq absent, broken once it
    # was added to ingest/requirements.txt for the deployed image.
    target_schema = client.get_table(target_table).schema
    job = client.load_table_from_dataframe(
        df,
        staging_table,
        job_config=bigquery.LoadJobConfig(schema=target_schema, write_disposition="WRITE_TRUNCATE"),
    )
    job.result()

    merge_sql = build_merge_sql(target_table, staging_table, list(df.columns), key_columns, scope)
    client.query(merge_sql).result()
    print(f"{table}: merged {len(df)} rows")
