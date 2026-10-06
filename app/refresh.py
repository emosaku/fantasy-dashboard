"""Starting the ingest job from the dashboard: a league's on-demand refresh, its
first data load after registration, and the purge after a delete.

All three run the same Cloud Run Job the daily schedule runs, with overrides:
LEAGUE_IDS limits it to one league (one task), PURGE_ONLY=1 only purges. The
dashboard's service account needs roles/run.jobsExecutorWithOverrides on that one
job. Pages wait for the data, not the job: ingest stamps the league's
last_ingested_at in Firestore when it finishes, so a newer stamp means it landed.
"""

import time

import google.auth
from google.auth.transport.requests import AuthorizedSession

import settings

RUN_API = "https://run.googleapis.com/v2"


def _session() -> AuthorizedSession:
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    if hasattr(credentials, "with_quota_project"):
        # Bill the API call to this project, not whatever gcloud's default project is.
        credentials = credentials.with_quota_project(settings.PROJECT)
    return AuthorizedSession(credentials)


def run_job(env: dict[str, str], session=None) -> None:
    """Start one execution of the ingest job, as one task, with these env overrides."""
    session = session or _session()
    url = (
        f"{RUN_API}/projects/{settings.PROJECT}/locations/{settings.REGION}"
        f"/jobs/{settings.INGEST_JOB}:run"
    )
    body = {
        "overrides": {
            "containerOverrides": [{"env": [{"name": k, "value": v} for k, v in env.items()]}],
            "taskCount": 1,
        }
    }
    response = session.post(url, json=body)
    response.raise_for_status()


def ingest_league(league_id: int, session=None) -> None:
    run_job({"LEAGUE_IDS": str(int(league_id))}, session)


def purge(session=None) -> None:
    run_job({"PURGE_ONLY": "1"}, session)


def wait_for(finished, poll_seconds: float = 5, timeout_seconds: float = 420) -> bool:
    """Poll finished() until True; False if it hasn't happened within the timeout (the
    job may still finish later)."""
    deadline = time.monotonic() + timeout_seconds
    while not finished():
        if time.monotonic() > deadline:
            return False
        time.sleep(poll_seconds)
    return True
