"""Manager logins (app/auth.py)."""

import re

import pytest

from auth import (
    LockedOut,
    Throttle,
    authenticate,
    check_password,
    hash_password,
    make_token,
    new_password,
    read_token,
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


SECRET = "server-side-secret"


def test_token_round_trip():
    users = make_users()
    token = make_token("eni.mosaku", users, SECRET, now=1000)
    assert read_token(token, users, SECRET, now=1000 + 86400)["username"] == "eni.mosaku"


def test_token_expires_after_30_days():
    users = make_users()
    token = make_token("eni.mosaku", users, SECRET, now=1000)
    assert read_token(token, users, SECRET, now=1000 + 31 * 86400) is None


def test_token_cannot_be_forged_or_extended():
    users = make_users()
    username, expires, signature = make_token("eni.mosaku", users, SECRET, now=1000).split("|")
    assert (
        read_token(f"{username}|{int(expires) + 10**6}|{signature}", users, SECRET, now=0) is None
    )
    assert read_token(f"chris.tetteh|{expires}|{signature}", users, SECRET, now=0) is None
    assert read_token(make_token("eni.mosaku", users, "other-secret"), users, SECRET) is None
    assert read_token("garbage", users, SECRET) is None
    assert read_token(None, users, SECRET) is None


def test_password_reset_invalidates_old_tokens():
    token = make_token("eni.mosaku", make_users(), SECRET, now=1000)
    reset = make_users(password="new-pass-word")  # new salt and hash
    assert read_token(token, reset, SECRET, now=2000) is None
