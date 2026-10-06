"""Kill switch decisions -- pure, so they're unit-tested without Google Cloud.

Cloud Billing publishes a budget notification to Pub/Sub several times a day: the
budget amount and the cost so far this month. When cost reaches the budget, the
switch trips: every Cloud Scheduler job is paused (no more ESPN pulls) and every
Cloud Run service stops accepting public traffic (allUsers loses run.invoker), so
nothing more can run up the bill. Turning it back on is deliberate and manual:
docs/multiLeagueDocs/killswitch.md.
"""

import base64
import json

ALL_USERS = "allUsers"
INVOKER = "roles/run.invoker"


def parse_budget_message(data_b64: str) -> dict:
    """The JSON body Cloud Billing sends, from the Pub/Sub message's base64 data."""
    return json.loads(base64.b64decode(data_b64).decode())


def should_trip(notification: dict, ratio: float = 1.0) -> bool:
    """True once this month's cost reaches `ratio` x the budget."""
    budget = float(notification.get("budgetAmount", 0) or 0)
    cost = float(notification.get("costAmount", 0) or 0)
    return budget > 0 and cost >= ratio * budget


def without_public_access(policy: dict) -> tuple[dict, bool]:
    """(policy with allUsers removed from run.invoker, whether anything changed)."""
    changed = False
    bindings = []
    for binding in policy.get("bindings", []):
        members = binding.get("members", [])
        if binding.get("role") == INVOKER and ALL_USERS in members:
            members = [m for m in members if m != ALL_USERS]
            changed = True
        if members:
            bindings.append({**binding, "members": members})
    return {**policy, "bindings": bindings}, changed
