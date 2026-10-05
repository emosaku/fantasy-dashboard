"""The login page and who's signed in -- the Streamlit side of app/auth.py.

Every page sits behind the login. A signed-in manager's team becomes the default
everywhere (Compare, Roster Strength, Trade Analyzer), and the Trade Analyzer is
locked to it: each manager gets recommendations for their own team. An admin (the
commissioner) can pick any team. Logins live in st.secrets (.streamlit/secrets.toml,
written by scripts/manage_logins.py); a browser refresh starts a new session, so it
asks again.
"""

import streamlit as st

from auth import LockedOut, Throttle, authenticate

FALLBACK_TEAM = 10  # only used if a page is somehow reached without a login


def users() -> dict:
    try:
        return {name: dict(user) for name, user in st.secrets["auth"]["users"].items()}
    except (KeyError, FileNotFoundError):
        return {}


@st.cache_resource
def throttle() -> Throttle:
    """One lockout tracker for the whole app, so reloading doesn't reset it."""
    return Throttle()


def current_user() -> dict | None:
    return st.session_state.get("user")


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
    st.rerun()


def sidebar_user(team_names) -> None:
    user = current_user()
    if not user:
        return
    team = team_names.get(user["team_id"], "")
    st.sidebar.caption(f"Signed in as **{user['name']}** · {team}")
    if st.sidebar.button("Log out", icon=":material/logout:"):
        st.session_state.clear()
        st.rerun()
