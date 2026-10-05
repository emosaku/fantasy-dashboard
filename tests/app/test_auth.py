"""Manager logins (app/auth.py)."""

import re

import pytest

from auth import (
    LockedOut,
    Throttle,
    authenticate,
    check_password,
    hash_password,
    new_password,
    username_for,
)


def make_users(password="k7mq-2vxd-p9ht"):
    salt, digest = hash_password(password)
    return {
        "eni.mosaku": {
            "name": "Eni Mosaku",
            "team_id": 10,
            "admin": True,
            "salt": salt,
            "hash": digest,
        },
    }


def test_hash_round_trip_and_salting():
    salt, digest = hash_password("secret")
    assert check_password("secret", salt, digest)
    assert not check_password("Secret", salt, digest)
    assert hash_password("secret")[1] != digest  # a new salt every time


def test_new_passwords_are_readable_and_unique():
    passwords = {new_password() for _ in range(200)}
    assert len(passwords) == 200
    assert all(re.fullmatch(r"[a-z2-9]{4}-[a-z2-9]{4}-[a-z2-9]{4}", p) for p in passwords)
    assert not any(c in "".join(passwords) for c in "01lio")


def test_usernames():
    assert username_for("Eni Mosaku") == "eni.mosaku"
    assert username_for("Ah Ma Dou") == "ah.ma.dou"
    assert username_for("  Timothy   Dantzler ") == "timothy.dantzler"
    assert username_for("José O'Neal-Smith") == "jose.onealsmith"


def test_authenticate_returns_the_user_without_secrets():
    user = authenticate(make_users(), " Eni.Mosaku ", "k7mq-2vxd-p9ht", Throttle())
    assert user == {"username": "eni.mosaku", "name": "Eni Mosaku", "team_id": 10, "admin": True}


def test_wrong_password_or_unknown_user_fails():
    throttle = Throttle()
    assert authenticate(make_users(), "eni.mosaku", "wrong", throttle) is None
    assert authenticate(make_users(), "nobody", "k7mq-2vxd-p9ht", throttle) is None


def test_lockout_after_five_failures_then_expires():
    users, throttle = make_users(), Throttle(max_failures=5, window_seconds=900)
    for i in range(5):
        assert authenticate(users, "eni.mosaku", "wrong", throttle, now=1000 + i) is None
    with pytest.raises(LockedOut):  # even the right password is refused while locked
        authenticate(users, "eni.mosaku", "k7mq-2vxd-p9ht", throttle, now=1010)
    assert authenticate(users, "eni.mosaku", "k7mq-2vxd-p9ht", throttle, now=1000 + 901) is not None


def test_success_clears_earlier_failures():
    users, throttle = make_users(), Throttle(max_failures=2)
    authenticate(users, "eni.mosaku", "wrong", throttle, now=1)
    authenticate(users, "eni.mosaku", "k7mq-2vxd-p9ht", throttle, now=2)
    assert authenticate(users, "eni.mosaku", "wrong", throttle, now=3) is None  # not locked
