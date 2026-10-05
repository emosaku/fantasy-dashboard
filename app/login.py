"""The login page and who's signed in -- the Streamlit side of app/auth.py.

Every page sits behind the login. A signed-in manager's team becomes the default
everywhere (Compare, Roster Strength, Trade Analyzer), and the Trade Analyzer is
locked to it: each manager gets recommendations for their own team. An admin (the
commissioner) can pick any team. Logins live in st.secrets (.streamlit/secrets.toml,
written by scripts/manage_logins.py).

Signing in also stores a signed 30-day token in a browser cookie, so a reload --
which phones do whenever you switch back to the browser -- doesn't ask again. Log out
clears it. Streamlit can read cookies (st.context.cookies, from the page's first
request) but not set them, so a tiny script in a 1-pixel st.iframe writes them.
"""

import json

import streamlit as st

from auth import LockedOut, Throttle, authenticate, make_token, read_token

FALLBACK_TEAM = 10  # only used if a page is somehow reached without a login
COOKIE = "fd_session"


def users() -> dict:
    try:
        return {name: dict(user) for name, user in st.secrets["auth"]["users"].items()}
    except (KeyError, FileNotFoundError):
        return {}


def _cookie_secret() -> str:
    try:
        return st.secrets["auth"]["cookie_secret"]
    except (KeyError, FileNotFoundError):
        return ""


@st.cache_resource
def throttle() -> Throttle:
    """One lockout tracker for the whole app, so reloading doesn't reset it."""
    return Throttle()


def _write_cookie(value: str, max_age_seconds: int) -> None:
    """Set (or, with max_age 0, delete) the session cookie in the browser. st.iframe
    runs an HTML string with same-origin access, so document.cookie is the site's.
    The HTML is fixed here; the only value in it is our own server-made token."""
    st.iframe(
        "<script>"
        f"document.cookie = {json.dumps(COOKIE)} + '=' + {json.dumps(value)}"
        f" + '; Path=/; Max-Age={max_age_seconds}; SameSite=Lax'"
        " + (location.protocol === 'https:' ? '; Secure' : '');"
        "</script>",
        height=1,
    )


def current_user() -> dict | None:
    """The signed-in manager: this session's, else a valid stay-signed-in cookie's."""
    user = st.session_state.get("user")
    if user is None and not st.session_state.get("signed_out"):
        user = read_token(st.context.cookies.get(COOKIE), users(), _cookie_secret())
        if user:
            st.session_state["user"] = user
    return user


def sync_cookie() -> None:
    """Writes or clears the cookie after sign-in / log out. Called on every run from
    Home.py, because the write has to render on the run after the state changes."""
    token = st.session_state.pop("cookie_to_set", None)
    if token:
        _write_cookie(token, 30 * 86400)
    if st.session_state.pop("cookie_to_clear", False):
        _write_cookie("", 0)


def my_team() -> int:
    user = current_user()
    return user["team_id"] if user else FALLBACK_TEAM


def is_admin() -> bool:
    user = current_user()
    return bool(user and user["admin"])


def login_page() -> None:
    st.title("League dashboard")
    if not users():
        st.error("Logins aren't set up yet. Run scripts/manage_logins.py.")
        return
    st.caption("Sign in with the username and password your commissioner sent you.")
    with st.form("login"):
        username = st.text_input("Username", placeholder="first.last")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if not submitted:
        return
    try:
        user = authenticate(users(), username, password, throttle())
    except LockedOut:
        st.error("Too many wrong passwords. Try again in 15 minutes.")
        return
    if user is None:
        st.error("Wrong username or password.")
        return
    st.session_state["user"] = user
    st.session_state.pop("signed_out", None)
    if _cookie_secret():
        st.session_state["cookie_to_set"] = make_token(user["username"], users(), _cookie_secret())
    st.rerun()


def sidebar_user(team_names) -> None:
    user = current_user()
    if not user:
        return
    team = team_names.get(user["team_id"], "")
    st.sidebar.caption(f"Signed in as **{user['name']}** · {team}")
    if st.sidebar.button("Log out", icon=":material/logout:"):
        st.session_state.clear()
        # This session's request still carries the old cookie, so remember not to
        # sign back in from it, and clear it in the browser.
        st.session_state["signed_out"] = True
        st.session_state["cookie_to_clear"] = True
        st.rerun()
