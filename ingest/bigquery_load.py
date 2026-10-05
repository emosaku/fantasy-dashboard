"""Idempotent load: stage the DataFrame, then MERGE into the target table.

Every table follows the same pattern (sql/ddl/*.sql documents each table's natural
key) so re-running ingest -- intentionally, or because Cloud Scheduler fires twice --
never duplicates rows.
"""

import pandas as pd
from google.cloud import bigquery


def merge_load(
    client: bigquery.Client,
    project: str,
    dataset: str,
    table: str,
    df: pd.DataFrame,
    key_columns: list[str],
) -> None:
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

    non_key_columns = [c for c in df.columns if c not in key_columns]
    on_clause = " AND ".join(f"T.{c} = S.{c}" for c in key_columns)
    update_clause = ", ".join(f"T.{c} = S.{c}" for c in non_key_columns)
    all_columns = ", ".join(df.columns)
    insert_values = ", ".join(f"S.{c}" for c in df.columns)

    merge_sql = f"""
    MERGE `{target_table}` T
    USING `{staging_table}` S
    ON {on_clause}
    WHEN MATCHED THEN UPDATE SET {update_clause}
    WHEN NOT MATCHED THEN INSERT ({all_columns}) VALUES ({insert_values})
    """
    client.query(merge_sql).result()
    print(f"{table}: merged {len(df)} rows")
