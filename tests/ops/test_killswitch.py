"""The budget kill switch's decisions (ops/killswitch/logic.py)."""

import base64
import json

from logic import parse_budget_message, should_trip, without_public_access


def encoded(body: dict) -> str:
    return base64.b64encode(json.dumps(body).encode()).decode()


def test_parses_the_billing_message():
    message = encoded({"budgetAmount": 5.0, "costAmount": 1.23, "currencyCode": "USD"})
    assert parse_budget_message(message)["costAmount"] == 1.23


def test_trips_only_at_the_budget():
    assert not should_trip({"budgetAmount": 5.0, "costAmount": 4.99})
    assert should_trip({"budgetAmount": 5.0, "costAmount": 5.0})
    assert should_trip({"budgetAmount": 5.0, "costAmount": 7.5})
    assert not should_trip({"budgetAmount": 0, "costAmount": 1.0})  # no budget set
    assert not should_trip({})


def test_removes_only_public_access():
    policy = {
        "etag": "abc",
        "bindings": [
            {"role": "roles/run.invoker", "members": ["allUsers", "serviceAccount:app@x"]},
            {"role": "roles/run.admin", "members": ["user:eni@x"]},
        ],
    }
    new, changed = without_public_access(policy)
    assert changed
    assert new["etag"] == "abc"  # kept, so the update is safe against races
    assert new["bindings"] == [
        {"role": "roles/run.invoker", "members": ["serviceAccount:app@x"]},
        {"role": "roles/run.admin", "members": ["user:eni@x"]},
    ]


def test_drops_a_binding_left_empty_and_leaves_closed_services_alone():
    only_public = {"bindings": [{"role": "roles/run.invoker", "members": ["allUsers"]}]}
    assert without_public_access(only_public) == ({"bindings": []}, True)
    already_closed = {"bindings": [{"role": "roles/run.admin", "members": ["user:eni@x"]}]}
    assert without_public_access(already_closed) == (already_closed, False)
