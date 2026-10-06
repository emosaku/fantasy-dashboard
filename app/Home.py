"""League Lab's entry point. Multipage app via st.navigation; the feature pages live
in app/pages/. Signed out, only the landing page, the invite page and the privacy
policy exist. Run locally from the repo root with:

    streamlit run app/Home.py
"""

import settings  # noqa: I001  (first: sets up the import path)
import streamlit as st

import league
import ui

st.set_page_config(page_title="League Lab", page_icon=":material/science:")

if settings.SHUTDOWN:
    st.title("League Lab has shut down")
    st.write(
        "League Lab is no longer running, and every league's data has been deleted. "
        "Thanks to everyone who used it."
    )
    st.stop()

PRIVACY = st.Page("pages/privacy.py", title="Privacy", icon=":material/policy:", url_path="privacy")
JOIN = st.Page("pages/join.py", title="Join a league", icon=":material/group_add:", url_path="join")


def landing() -> None:
    st.title("League Lab")
    st.subheader("The analysis ESPN doesn't show you, for your fantasy basketball league.")
    st.markdown(
        "- **Power rankings by all-play**: your record if you'd played everyone, every week\n"
        "- **Luck**: who's winning more than their stats say\n"
        "- **Trade analyzer**: win-win trades and waiver moves for *your* categories\n"
        "- **Category and player rankings**, **head-to-head compare**, **every transaction**"
    )
    st.caption(
        "For head-to-head categories leagues (Most Categories or Each Category), any "
        "category set. Public or private leagues. Free, no ads."
    )
    if not league.auth_configured() and not settings.DEV_AUTH_EMAIL:
        st.warning("Sign-in isn't set up on this server yet.")
        return
    if st.button("Sign in with Google", type="primary", icon=":material/login:"):
        league.sign_in()
    st.caption(
        "Have an invite link? Sign in first, then open the link again. Signing in shares "
        "only your name and email with League Lab."
    )


def home() -> None:
    ctx = league.current()
    st.title(ctx.name)
    st.caption(
        f"{ctx.season} season · {ctx.scoring_label} · {len(ctx.cats)} categories: "
        + ", ".join(c.label for c in ctx.cats)
    )
    import queries  # here, so signed-out visitors never touch BigQuery

    standings = queries.teams(ctx.league_id, ctx.version).sort_values(["standing", "team_name"])
    standings["Record"] = (
        standings["wins"].astype(str)
        + "-"
        + standings["losses"].astype(str)
        + "-"
        + standings["ties"].astype(str)
    )
    standings["You"] = standings["team_id"].map(lambda t: "●" if t == ctx.my_team else "")
    st.subheader("Standings")
    st.dataframe(
        standings[["standing", "team_name", "You", "Record", "owner"]],
        column_config={
            "standing": st.column_config.NumberColumn("#", width="small"),
            "team_name": "Team",
            "You": st.column_config.TextColumn("", width="small"),
            "owner": "Manager",
        },
        hide_index=True,
        width="stretch",
        height=ui.table_height(len(standings)),
    )

    st.subheader("Pages")
    for page, blurb in PAGE_BLURBS:
        st.page_link(page)
        st.caption(blurb)


PAGES = {
    "compare": st.Page("pages/1_Compare.py", title="Compare", icon=":material/compare_arrows:"),
    "power": st.Page(
        "pages/2_Power_Rankings.py", title="Power Rankings", icon=":material/leaderboard:"
    ),
    "luck": st.Page(
        "pages/3_Matchups_and_Luck.py", title="Matchups and Luck", icon=":material/casino:"
    ),
    "txn": st.Page("pages/4_Transactions.py", title="Transactions", icon=":material/swap_horiz:"),
    "strength": st.Page(
        "pages/5_Roster_Strength.py", title="Roster Strength", icon=":material/fitness_center:"
    ),
    "trade": st.Page(
        "pages/6_Trade_Analyzer.py", title="Trade Analyzer", icon=":material/handshake:"
    ),
    "players": st.Page(
        "pages/7_Player_Rankings.py", title="Player Rankings", icon=":material/person_search:"
    ),
}
PAGE_BLURBS = [
    (PAGES["compare"], "Any two teams, category by category, for a week or the season."),
    (PAGES["power"], "Rankings by all-play: your record if you'd played everyone every week."),
    (PAGES["luck"], "Every matchup's scoreboard, and who's winning more than their stats say."),
    (PAGES["txn"], "Every add, drop, trade and lineup move, filterable."),
    (PAGES["strength"], "How each roster stacks up in every category, by recent form."),
    (PAGES["trade"], "Your best waiver pickups and win-win trades, and a mock-trade simulator."),
    (PAGES["players"], "Every player ranked in every category, rostered or free agent."),
]

user = league.current_user()
if user is None:
    st.navigation(
        [
            st.Page(landing, title="League Lab", icon=":material/science:", default=True),
            JOIN,
            PRIVACY,
        ],
        position="hidden",
    ).run()
    ui.footer()
    st.stop()

nav = st.navigation(
    {
        "": [st.Page(home, title="Home", icon=":material/home:", default=True)],
        "Analysis": list(PAGES.values()),
        "Leagues": [
            st.Page("pages/league_admin.py", title="League settings", icon=":material/tune:",
                    url_path="league"),
            st.Page("pages/register.py", title="Register a league", icon=":material/add:",
                    url_path="register"),
            JOIN,
            PRIVACY,
        ],
    }
)  # fmt: skip

# Sidebar: which league, who's signed in, and the open league's data freshness.
ids = league.open_league_ids()
if ids:
    league.selected_league_id()  # makes sure session_state["league_id"] is one of ids
    if len(ids) > 1:
        st.sidebar.selectbox(
            "League",
            ids,
            format_func=lambda i: (league.league_doc(i) or {}).get("league_name") or f"League {i}",
            key="league_id",
        )
    ctx = league.build_context(st.session_state["league_id"])
    if ctx is not None:
        ui.sidebar_league(ctx)
st.sidebar.caption(f"Signed in as **{user['name']}**")
if st.sidebar.button("Sign out", icon=":material/logout:"):
    league.sign_out()

nav.run()
ui.footer()
