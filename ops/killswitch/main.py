"""Budget kill switch for League Lab: a Cloud Run function on the budget-alerts
Pub/Sub topic. When the month's cost reaches the budget it pauses every Cloud
Scheduler job and removes public access from every Cloud Run service in the
project's region. Logic: logic.py. Runbook: docs/multiLeagueDocs/killswitch.md.
"""

import os

import functions_framework
import google.auth
from google.auth.transport.requests import AuthorizedSession
from logic import parse_budget_message, should_trip, without_public_access

PROJECT = os.environ["PROJECT_ID"]
REGION = os.environ.get("REGION", "us-west1")
RUN = "https://run.googleapis.com/v2"
SCHEDULER = "https://cloudscheduler.googleapis.com/v1"


def _session() -> AuthorizedSession:
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return AuthorizedSession(credentials)


def pause_schedulers(session) -> list[str]:
    parent = f"projects/{PROJECT}/locations/{REGION}"
    jobs = session.get(f"{SCHEDULER}/{parent}/jobs").json().get("jobs", [])
    paused = []
    for job in jobs:
        if job.get("state") == "ENABLED":
            session.post(f"{SCHEDULER}/{job['name']}:pause").raise_for_status()
            paused.append(job["name"])
    return paused


def close_services(session) -> list[str]:
    parent = f"projects/{PROJECT}/locations/{REGION}"
    services = session.get(f"{RUN}/{parent}/services").json().get("services", [])
    closed = []
    for service in services:
        name = service["name"]
        policy = session.get(f"{RUN}/{name}:getIamPolicy").json()
        new_policy, changed = without_public_access(policy)
        if changed:
            session.post(
                f"{RUN}/{name}:setIamPolicy", json={"policy": new_policy}
            ).raise_for_status()
            closed.append(name)
    return closed


@functions_framework.cloud_event
def on_budget(event):
    notification = parse_budget_message(event.data["message"]["data"])
    cost, budget = notification.get("costAmount"), notification.get("budgetAmount")
    if not should_trip(notification):
        print(f"Budget check: {cost} of {budget} -- under budget, nothing to do.")
        return
    session = _session()
    paused, closed = pause_schedulers(session), close_services(session)
    print(f"KILL SWITCH TRIPPED: {cost} of {budget}. Paused {paused}; closed {closed}.")
