"""Where League Lab runs, from the environment -- no project is hard-coded.

Cloud Run sets these on the service; locally they come from .env (git-ignored).
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # local development only

# The repo root, so the app can import the ingest package's ESPN client and category
# catalog (the dashboard image copies both). Streamlit only puts app/ on the path.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PROJECT = os.environ.get("GCP_PROJECT_ID", "")
DATASET = os.environ.get("BIGQUERY_DATASET", "league_lab")
LOCATION = os.environ.get("BIGQUERY_LOCATION", "us-west1")
REGION = os.environ.get("GCP_REGION", "us-west1")
INGEST_JOB = os.environ.get("INGEST_JOB", "league-ingest")
SEASON = int(os.environ.get("SEASON", "2027"))  # ESPN names a season by the year it ends

# Sign-in without Google, for running the app on your own machine only: set
# DEV_AUTH_EMAIL in .env. Ignored on Cloud Run (K_SERVICE is always set there).
ON_CLOUD_RUN = "K_SERVICE" in os.environ
DEV_AUTH_EMAIL = "" if ON_CLOUD_RUN else os.environ.get("DEV_AUTH_EMAIL", "")

# The teardown switch: set SHUTDOWN=1 on the service and every page shows the
# shutdown notice instead (scripts/teardown.py does this).
SHUTDOWN = os.environ.get("SHUTDOWN", "") == "1"

# Phase 1 caps: how many leagues the site accepts in all, and per person.
MAX_LEAGUES = int(os.environ.get("MAX_LEAGUES", "10"))
MAX_LEAGUES_PER_USER = int(os.environ.get("MAX_LEAGUES_PER_USER", "3"))
