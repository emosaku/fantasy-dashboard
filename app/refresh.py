"""On-demand data refresh: runs the same espn-ingest Cloud Run Job that Cloud
Scheduler runs every morning, and waits for it to finish. Goes alongside the daily
schedule, not instead of it.

Uses whatever Google credentials the app runs with -- your gcloud login locally, the
dashboard's service account on Cloud Run, which needs only run.jobs.run on that one
job (roles/run.invoker). It doesn't watch the job itself -- that would need
run.operations.get, grantable only project-wide -- but waits for the data: ingest
writes league_status last, so a newer timestamp there means the whole refresh has
landed. A cooldown after the last update keeps the shared link from hammering ESPN.
"""

import datetime as dt
import os
import time

import google.auth
from google.auth.transport.requests import AuthorizedSession

PROJECT = os.environ.get("GCP_PROJECT_ID", "fantasy-dash-emk")
REGION = os.environ.get("GCP_REGION", "us-west1")
JOB = os.environ.get("INGEST_JOB", "espn-ingest")
COOLDOWN = dt.timedelta(minutes=10)
RUN_API = "https://run.googleapis.com/v2"


def can_refresh(last_updated, now=None) -> bool:
    """False within COOLDOWN of the last ingest (a NaN/None last_updated -> True)."""
    if last_updated is None:
        return True
    now = now or dt.datetime.now(dt.UTC)
    return now - last_updated >= COOLDOWN


def _session() -> AuthorizedSession:
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    if hasattr(credentials, "with_quota_project"):
        # Bill the API call to this project, not whatever gcloud's default project is.
        credentials = credentials.with_quota_project(PROJECT)
    return AuthorizedSession(credentials)


def run_ingest(
    finished, session=None, poll_seconds: float = 5, timeout_seconds: float = 600
) -> None:
    """Start the ingest job, then block until finished() returns True (the new data
    has landed). Raises RuntimeError if it hasn't within timeout_seconds -- the job
    may still finish later; a failed run triggers the ingest failure alert."""
    session = session or _session()
    url = f"{RUN_API}/projects/{PROJECT}/locations/{REGION}/jobs/{JOB}:run"
    response = session.post(url, json={})
    response.raise_for_status()

    deadline = time.monotonic() + timeout_seconds
    while not finished():
        if time.monotonic() > deadline:
            raise RuntimeError(
                "The refresh is taking longer than expected. The data will update when "
                "it finishes; check back in a few minutes."
            )
        time.sleep(poll_seconds)
