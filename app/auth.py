"""Manager logins: password hashing, checking, and a lockout after repeated failures.

Pure Python (the standard library's scrypt), no Streamlit, so it's unit-tested.
Passwords are never stored: each login keeps a random salt and the scrypt hash of
salt + password, in .streamlit/secrets.toml (git-ignored), written by
scripts/manage_logins.py. Checking re-hashes the typed password and compares in
constant time.
"""

import hashlib
import hmac
import re
import secrets
import time
import unicodedata
from dataclasses import dataclass, field

SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}
# Easy to read aloud or copy by hand: no 0/o, 1/l/i.
PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def new_password(groups: int = 3, size: int = 4) -> str:
    """e.g. 'k7mq-2vxd-p9ht': 12 random characters, about 59 bits."""
    return "-".join(
        "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(size)) for _ in range(groups)
    )


def hash_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    """(salt, hash) as hex strings. A new random salt unless one is given."""
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **SCRYPT)
    return salt.hex(), digest.hex()


def check_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    _, candidate = hash_password(password, salt_hex)
    return hmac.compare_digest(candidate, hash_hex)


def username_for(full_name: str) -> str:
    """'Eni Mosaku' -> 'eni.mosaku'; accents dropped, anything else non-alphanumeric
    removed, words joined by dots."""
    ascii_name = unicodedata.normalize("NFKD", full_name).encode("ascii", "ignore").decode()
    words = [re.sub(r"[^a-z0-9]", "", w) for w in ascii_name.lower().split()]
    return ".".join(w for w in words if w)


@dataclass
class Throttle:
    """Locks a username after max_failures wrong passwords within window_seconds, so
    a login-free-to-reach page can't be brute-forced. Shared across all sessions
    (the app keeps one instance), so reloading the page doesn't reset it."""

    max_failures: int = 5
    window_seconds: float = 15 * 60
    failures: dict = field(default_factory=dict)

    def _recent(self, username: str, now: float) -> list[float]:
        recent = [t for t in self.failures.get(username, []) if now - t < self.window_seconds]
        self.failures[username] = recent
        return recent

    def locked(self, username: str, now: float | None = None) -> bool:
        return len(self._recent(username, now or time.time())) >= self.max_failures

    def record_failure(self, username: str, now: float | None = None) -> None:
        now = now or time.time()
        self._recent(username, now).append(now)

    def reset(self, username: str) -> None:
        self.failures.pop(username, None)


class LockedOut(Exception):
    pass


def authenticate(users: dict, username: str, password: str, throttle: Throttle, now=None):
    """The user's record without its salt and hash on success, None on a wrong
    username or password. Raises LockedOut after too many failures."""
    username = username.strip().lower()
    if throttle.locked(username, now):
        raise LockedOut(username)
    user = users.get(username)
    if user and check_password(password, user["salt"], user["hash"]):
        throttle.reset(username)
        return {
            "username": username,
            "name": user["name"],
            "team_id": int(user["team_id"]),
            "admin": bool(user.get("admin", False)),
        }
    throttle.record_failure(username, now)
    return None


# --- Staying signed in --------------------------------------------------------------
# A phone often reloads the page when you come back to the browser, which starts a new
# Streamlit session. To keep managers signed in across that, the browser keeps a
# signed token in a cookie: "username|expires|signature". The signature is an HMAC
# with a secret only the server knows (secrets.toml), over the username, the expiry
# and part of the user's password hash -- so it can't be forged or extended, and
# resetting a password invalidates every token issued before.

TOKEN_DAYS = 30


def _token_signature(username: str, expires: int, password_hash: str, secret: str) -> str:
    message = f"{username}|{expires}|{password_hash[:16]}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def make_token(username: str, users: dict, secret: str, now: float | None = None) -> str:
    expires = int((time.time() if now is None else now) + TOKEN_DAYS * 86400)
    signature = _token_signature(username, expires, users[username]["hash"], secret)
    return f"{username}|{expires}|{signature}"


def read_token(token: str | None, users: dict, secret: str, now: float | None = None):
    """The user's record (as authenticate returns it) for a valid, unexpired token,
    else None."""
    try:
        username, expires, signature = (token or "").split("|")
        expires = int(expires)
    except ValueError:
        return None
    user = users.get(username)
    if not user or not secret or expires < (time.time() if now is None else now):
        return None
    expected = _token_signature(username, expires, user["hash"], secret)
    if not hmac.compare_digest(expected, signature):
        return None
    return {
        "username": username,
        "name": user["name"],
        "team_id": int(user["team_id"]),
        "admin": bool(user.get("admin", False)),
    }
