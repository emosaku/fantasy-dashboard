"""Streamlit entry point (Step 6). Multipage app via the st.navigation pages API;
the six feature pages live in app/pages/. Everything sits behind a manager login
(app/login.py); until someone signs in, the login page is the only page. Run
locally with:

    streamlit run app/Home.py

Deployed as a Cloud Run service in Step 7.
"""

import streamlit as st

import login
import queries
import ui

st.set_page_config(page_title="Fantasy Dashboard", page_icon=":material/sports_basketball:")


def home() -> None:
    st.title("League dashboard")
    st.caption("Everything ESPN doesn't show you, refreshed every morning.")

    standings = queries.teams().sort_values(["standing", "team_name"])
    standings["Record"] = (
        standings["wins"].astype(str)
        + "-"
        + standings["losses"].astype(str)
        + "-"
        + standings["ties"].astype(str)
    )
    st.subheader("Standings")
    st.dataframe(
        standings[["standing", "team_name", "Record", "owner"]],
        column_config={
            "standing": st.column_config.NumberColumn("#", width="small"),
            "team_name": "Team",
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
}
PAGE_BLURBS = [
    (PAGES["compare"], "Any two teams, category by category, for a week or the season."),
    (PAGES["power"], "Rankings by all-play: your record if you'd played everyone every week."),
    (PAGES["luck"], "Every matchup's scoreboard, and who's winning more than their stats say."),
    (PAGES["txn"], "Every add, drop, trade and lineup move, filterable."),
    (PAGES["strength"], "How each roster stacks up in every category, by recent form."),
    (PAGES["trade"], "Your best waiver pickups and win-win trades, and a mock-trade simulator."),
]

login.sync_cookie()
if login.current_user() is None:
    st.navigation([st.Page(login.login_page, title="Sign in", icon=":material/login:")]).run()
    st.stop()

nav = st.navigation(
    [st.Page(home, title="Home", icon=":material/home:", default=True), *PAGES.values()]
)
login.sidebar_user(queries.teams().set_index("team_id")["team_name"].str.strip())
ui.sidebar_freshness()
nav.run()
