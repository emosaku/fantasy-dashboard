"""Loading one league's rows into BigQuery without touching other leagues.

Each load goes to a short-lived staging table (a free load job, schema pinned to the
target's so types never drift), then one script replaces the league's rows:

    DELETE FROM target WHERE <scope>;  INSERT INTO target SELECT ... FROM staging;

<scope> is always within one league (league_id = X, plus e.g. the matchup periods
re-fetched), and tables are clustered by league_id, so both statements read only that
league's blocks. Re-running a load gives the same rows -- idempotent, like the
single-league MERGE it replaces, but cheaper per league. An empty DataFrame changes
nothing: a failed or empty pull never wipes a league's data.
"""

import datetime as dt
import numbers
import uuid

import pandas as pd
from google.cloud import bigquery

STAGING_HOURS = 2


def stage(client: bigquery.Client, target: str, df: pd.DataFrame) -> str:
    """Load df into a new staging table shaped like `target`; returns its id."""
    staging = f"{target}__stage_{uuid.uuid4().hex[:12]}"
    schema = client.get_table(target).schema
    client.load_table_from_dataframe(
        df[[f.name for f in schema]],
        staging,
        job_config=bigquery.LoadJobConfig(schema=schema, write_disposition="WRITE_TRUNCATE"),
    ).result()
    table = client.get_table(staging)
    table.expires = dt.datetime.now(dt.UTC) + dt.timedelta(hours=STAGING_HOURS)
    client.update_table(table, ["expires"])
    return staging


def replace_sql(target: str, staging: str, columns: list[str], scope: str) -> str:
    cols = ", ".join(columns)
    return (
        f"DELETE FROM `{target}` WHERE {scope};\n"
        f"INSERT INTO `{target}` ({cols}) SELECT {cols} FROM `{staging}`;"
    )


def replace_rows(client, project, dataset, table, df: pd.DataFrame, scope: str) -> int:
    """Replace the rows matching `scope` (SQL over the target's columns, always
    including league_id) with df's rows. Returns rows written."""
    if df.empty:
        print(f"{table}: nothing to load")
        return 0
    target = f"{project}.{dataset}.{table}"
    staging = stage(client, target, df)
    try:
        columns = [f.name for f in client.get_table(target).schema]
        client.query(replace_sql(target, staging, columns, scope)).result()
    finally:
        client.delete_table(staging, not_found_ok=True)
    print(f"{table}: {len(df)} rows")
    return len(df)


def league_scope(league_id: int, extra: str = "") -> str:
    scope = f"league_id = {int(league_id)}"
    return f"{scope} AND {extra}" if extra else scope


def in_list(column: str, values) -> str:
    """`column IN (...)` for ints or strings (quoted), for replace scopes."""
    rendered = ", ".join(
        str(int(v)) if isinstance(v, numbers.Integral) else "'" + str(v).replace("'", "") + "'"
        for v in values
    )
    return f"{column} IN ({rendered})"
