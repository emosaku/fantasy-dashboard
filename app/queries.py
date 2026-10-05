"""Maps each dashboard page to its BigQuery view (Step 6). Pages import from here
and never contain raw SQL directly, so renaming a view or adding a filter is a
one-file change.

Every read is cached for an hour: the data only changes once a day (Step 4's 5 AM
ingest), so page clicks never re-hit BigQuery. Each query is limited to the latest
season, so last year's rows never leak into this year's pages.
"""

import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()  # local development only; Cloud Run sets these as real env vars
PROJECT = os.environ.get("GCP_PROJECT_ID", "fantasy-dash-emk")
DATASET = os.environ.get("BIGQUERY_DATASET", "fantasy")


@st.cache_resource
def _client() -> bigquery.Client:
    return bigquery.Client(project=PROJECT)


@st.cache_data(ttl=3600, show_spinner="Loading league data...")
def _read(sql: str) -> pd.DataFrame:
    df = _client().query(sql).to_dataframe(create_bqstorage_client=False)
    # ESPN keeps whatever spacing a manager typed, trailing spaces included -- which
    # breaks Markdown bold (`**Name **`) and makes names look misaligned.
    for col in ("team_name", "opponent_name"):
        if col in df:
            df[col] = df[col].str.strip()
    return df


def _table(name: str) -> str:
    return f"`{PROJECT}.{DATASET}.{name}`"


def _current_season(view: str) -> pd.DataFrame:
    t = _table(view)
    return _read(f"SELECT * FROM {t} WHERE season = (SELECT MAX(season) FROM {t})")


def teams() -> pd.DataFrame:
    """Latest snapshot of each team: name and real record. Home page, and the team
    names v_team_week_cats doesn't carry."""
    t = _table("teams")
    return _read(f"""
        SELECT team_id, team_name, owner, wins, losses, ties, standing
        FROM {t}
        WHERE season = (SELECT MAX(season) FROM {t})
        QUALIFY ROW_NUMBER() OVER (PARTITION BY team_id ORDER BY snapshot_date DESC) = 1
    """)


def last_updated() -> pd.Timestamp | None:
    """When the ingest job last wrote data -- shown in the sidebar on every page."""
    df = _read(f"SELECT MAX(ingested_at) AS ts FROM {_table('teams')}")
    ts = df["ts"].iloc[0]
    return None if pd.isna(ts) else ts


def team_week_cats() -> pd.DataFrame:
    """Compare page."""
    return _current_season("v_team_week_cats")


def power_rankings() -> pd.DataFrame:
    """Power Rankings page."""
    return _current_season("v_power_rankings")


def luck() -> pd.DataFrame:
    """Matchups and Luck page (with team_week_cats for the scoreboard values)."""
    return _current_season("v_luck")


def transactions() -> pd.DataFrame:
    """Transactions page."""
    return _current_season("v_transactions")


def roster_strength() -> pd.DataFrame:
    """Roster Strength page."""
    return _current_season("v_roster_strength")


def team_roster_stats() -> pd.DataFrame:
    """Trade Analyzer page."""
    return _current_season("v_team_roster_stats")
