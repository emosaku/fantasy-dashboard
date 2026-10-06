"""Every BigQuery read the dashboard makes. Pages never contain SQL.

The dashboard reads only the small precomputed m_* tables (ingest refreshes them per
league; see ingest/materialize.py), always for one league, as a query parameter --
so a page can't read another league's rows, and each query scans one league's
clustered blocks.

Reads are cached per (league, data version): `version` is the league's
last_ingested_at, so new data shows up as soon as it lands and the cache is never
cleared by hand. Within a version, nothing re-hits BigQuery.
"""

import pandas as pd
import streamlit as st
from google.cloud import bigquery

import settings


@st.cache_resource
def _client() -> bigquery.Client:
    return bigquery.Client(project=settings.PROJECT, location=settings.LOCATION)


@st.cache_data(ttl=6 * 3600, max_entries=400, show_spinner="Loading league data...")
def _read(table: str, league_id: int, version: str) -> pd.DataFrame:
    sql = (
        f"SELECT * FROM `{settings.PROJECT}.{settings.DATASET}.{table}` "
        "WHERE league_id = @league_id"
    )
    config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("league_id", "INT64", int(league_id))]
    )
    df = _client().query(sql, job_config=config).to_dataframe(create_bqstorage_client=False)
    # ESPN keeps whatever spacing a manager typed, trailing spaces included.
    for col in ("team_name", "opponent_name", "player_name"):
        if col in df:
            df[col] = df[col].str.strip()
    return df


def team_week_cats(league_id: int, version: str) -> pd.DataFrame:
    """Compare, Matchups: each team's value per category per week (long)."""
    return _read("m_team_week_cats", league_id, version)


def all_play(league_id: int, version: str) -> pd.DataFrame:
    return _read("m_all_play", league_id, version)


def power_rankings(league_id: int, version: str) -> pd.DataFrame:
    return _read("m_power_rankings", league_id, version)


def luck(league_id: int, version: str) -> pd.DataFrame:
    return _read("m_luck", league_id, version)


def transactions(league_id: int, version: str) -> pd.DataFrame:
    return _read("m_transactions", league_id, version)


def player_pool(league_id: int, version: str) -> pd.DataFrame:
    """Per-game stat lines (long: player x stat window x stat)."""
    return _read("m_player_pool", league_id, version)


def player_z(league_id: int, version: str) -> pd.DataFrame:
    """Every pool player's z per category per stat window (long)."""
    return _read("m_player_z", league_id, version)


def category_ranks(league_id: int, version: str) -> pd.DataFrame:
    return _read("m_category_ranks", league_id, version)


def player_profile(league_id: int, version: str) -> pd.DataFrame:
    return _read("m_player_profile", league_id, version)


def roster_strength(league_id: int, version: str) -> pd.DataFrame:
    return _read("m_roster_strength", league_id, version)


def teams(league_id: int, version: str) -> pd.DataFrame:
    """Each team's name, manager and real record (a raw table, one row per team)."""
    return _read("teams", league_id, version)
