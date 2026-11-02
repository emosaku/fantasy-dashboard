"""Who's calling: every request carries a sign-in token (OpenID Connect ID token) in
`Authorization: Bearer ...`, checked here and nowhere else.

The provider is configuration, not code, so Whop or Google (backlog R9, decided by the
Phase 1 spike) plugs in by setting OIDC_ISSUER and OIDC_AUDIENCE: the signing keys
come from the issuer's own discovery document, and the token must be signed by one of
them, unexpired, issued by that issuer and meant for us (audience). The user id is the
token's `sub`, the same id Streamlit's st.login stores (tenancy uses it as uid), so
the two front ends share one set of memberships.

Locally, DEV_AUTH_EMAIL stands in for sign-in exactly as in app/settings.py, and only
off Cloud Run. Tests use a test issuer with its own key (tests/api/conftest.py).
Tokens are never logged.
"""

import os
from dataclasses import dataclass

import jwt
import requests

ALGORITHMS = ["RS256", "ES256"]


class NotSignedIn(Exception):
    """No token, or one that isn't valid; the message is safe to show."""


@dataclass(frozen=True)
class User:
    uid: str
    email: str
    name: str


class Verifier:
    """Checks tokens from one issuer. `keys` is a PyJWKClient-like object with
    get_signing_key_from_jwt(token); by default it's built from the issuer's
    discovery document (fetched once)."""

    def __init__(self, issuer: str, audience: str, keys=None):
        self.issuer, self.audience = issuer.rstrip("/"), audience
        self._keys = keys

    def _signing_keys(self):
        if self._keys is None:
            config = requests.get(f"{self.issuer}/.well-known/openid-configuration", timeout=10)
            config.raise_for_status()
            self._keys = jwt.PyJWKClient(config.json()["jwks_uri"], cache_keys=True)
        return self._keys

    def verify(self, token: str) -> User:
        try:
            key = self._signing_keys().get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=ALGORITHMS,
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iss", "sub"]},
            )
        except (jwt.PyJWTError, KeyError) as error:
            raise NotSignedIn("Your sign-in isn't valid; sign in again.") from error
        email = claims.get("email", "")
        return User(uid=str(claims["sub"]), email=email,
                    name=claims.get("name") or email or str(claims["sub"]))  # fmt: skip


class DevVerifier:
    """Local development only: everyone is DEV_AUTH_EMAIL (refused on Cloud Run), with
    or without a token."""

    dev = True

    def __init__(self, email: str):
        if "K_SERVICE" in os.environ:
            raise RuntimeError("DEV_AUTH_EMAIL is for local development only")
        self.user = User(uid=f"dev:{email}", email=email, name=email.split("@")[0])

    def verify(self, token: str) -> User:
        return self.user


def from_env(env=os.environ):
    """The verifier the environment configures: DEV_AUTH_EMAIL off Cloud Run, else the
    OIDC issuer. With neither, every request is refused."""
    if env.get("DEV_AUTH_EMAIL") and "K_SERVICE" not in env:
        return DevVerifier(env["DEV_AUTH_EMAIL"])
    if env.get("OIDC_ISSUER") and env.get("OIDC_AUDIENCE"):
        return Verifier(env["OIDC_ISSUER"], env["OIDC_AUDIENCE"])
    return None


def bearer(header: str | None) -> str:
    if not header or not header.lower().startswith("bearer "):
        raise NotSignedIn("Sign in first.")
    return header.split(" ", 1)[1].strip()
