"""The one BigQuery read both front ends share: a league's rows of one table.

Plain Python (no Streamlit), so the Streamlit pages (queries.py, cached per data
version) and the API (api/store.py, its own cache) read exactly the same way: always
one league, as a query parameter, so a request can't read another league's rows.
"""

import pandas as pd
from google.cloud import bigquery

NAME_COLUMNS = ("team_name", "opponent_name", "player_name")


def league_rows(client: bigquery.Client, project: str, dataset: str, table: str,
                league_id: int) -> pd.DataFrame:  # fmt: skip
    sql = f"SELECT * FROM `{project}.{dataset}.{table}` WHERE league_id = @league_id"
    config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("league_id", "INT64", int(league_id))]
    )
    df = client.query(sql, job_config=config).to_dataframe(create_bqstorage_client=False)
    # ESPN keeps whatever spacing a manager typed, trailing spaces included.
    for col in NAME_COLUMNS:
        if col in df:
            df[col] = df[col].str.strip()
    return df
