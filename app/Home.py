"""League Lab's entry point. Multipage app via st.navigation; the feature pages live
in app/views/ (categories leagues) and app/views/points/ (points leagues: same page
names and addresses, Transactions shared). The open league's format picks the set.
Signed out, only the landing page, the invite page and the privacy policy exist.
Run locally from the repo root with:

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

# Page files must not live in a folder named pages/: with one next to this file, a fresh
# server process serves each of them straight from its URL, skipping the sign-in gate.
PRIVACY = st.Page("views/privacy.py", title="Privacy", icon=":material/policy:", url_path="privacy")
JOIN = st.Page("views/join.py", title="Join a league", icon=":material/group_add:", url_path="join")
DRAFT = st.Page("views/draft.py", title="Draft", icon=":material/format_list_numbered:",
                url_path="Draft")  # fmt: skip


def landing() -> None:
    st.title("League Lab")
    st.subheader("The analysis ESPN doesn't show you, for your fantasy basketball league.")
    st.markdown(
        "- **Power rankings by all-play**: your record if you'd played everyone, every week\n"
        "- **Luck**: who's winning more than their stats say\n"
        "- **Trade analyzer**: win-win trades and waiver moves for *your* team\n"
        "- **Player rankings**, **head-to-head compare**, **every transaction**"
    )
    st.caption(
        "For head-to-head points leagues and head-to-head categories leagues (Most "
        "Categories or Each Category, any category set). Public or private leagues. "
        "Free, no ads."
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
    if ctx.is_points:
        from points import home as points_home

        points_home.render(ctx)
        st.subheader("Pages")
        for page, blurb in POINTS_BLURBS:
            st.page_link(page)
            st.caption(blurb)
        return
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
    "compare": st.Page("views/1_Compare.py", title="Compare", icon=":material/compare_arrows:"),
    "power": st.Page(
        "views/2_Power_Rankings.py", title="Power Rankings", icon=":material/leaderboard:"
    ),
    "luck": st.Page(
        "views/3_Matchups_and_Luck.py", title="Matchups and Luck", icon=":material/casino:"
    ),
    "txn": st.Page("views/4_Transactions.py", title="Transactions", icon=":material/swap_horiz:"),
    "strength": st.Page(
        "views/5_Roster_Strength.py", title="Roster Strength", icon=":material/fitness_center:"
    ),
    "trade": st.Page(
        "views/6_Trade_Analyzer.py", title="Trade Analyzer", icon=":material/handshake:"
    ),
    "players": st.Page(
        "views/7_Player_Rankings.py", title="Player Rankings", icon=":material/person_search:"
    ),
}
POINTS_PAGES = {
    "compare": st.Page(
        "views/points/1_Compare.py", title="Compare", icon=":material/compare_arrows:"
    ),
    "power": st.Page(
        "views/points/2_Power_Rankings.py", title="Power Rankings", icon=":material/leaderboard:"
    ),
    "luck": st.Page(
        "views/points/3_Matchups_and_Luck.py", title="Matchups and Luck", icon=":material/casino:"
    ),
    "txn": PAGES["txn"],
    "strength": st.Page(
        "views/points/5_Roster_Strength.py", title="Roster Strength",
        icon=":material/fitness_center:",
    ),
    "trade": st.Page(
        "views/points/6_Trade_Analyzer.py", title="Trade Analyzer", icon=":material/handshake:"
    ),
    "players": st.Page(
        "views/points/7_Player_Rankings.py", title="Player Rankings",
        icon=":material/person_search:",
    ),
}  # fmt: skip
POINTS_BLURBS = [
    (POINTS_PAGES["compare"], "Two teams' weekly points side by side, or up to four players."),
    (POINTS_PAGES["power"], "Rankings by all-play points, and each team's projected finish."),
    (POINTS_PAGES["luck"], "Every week's scores, and who's winning more than their points say."),
    (POINTS_PAGES["txn"], "Every add, drop, trade and lineup move, filterable."),
    (POINTS_PAGES["strength"], "Each roster's projected weekly points from a daily lineup."),
    (POINTS_PAGES["trade"], "Waiver pickups and win-win trades in expected wins a week."),
    (POINTS_PAGES["players"], "Every player by fantasy points per game, rostered or free agent."),
]
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

# The open league's format picks the page set (same names and addresses in both).
ids = league.open_league_ids()
analysis_pages = PAGES
if ids and league.league_format(league.league_doc(league.selected_league_id())) == "points":
    analysis_pages = POINTS_PAGES

nav = st.navigation(
    {
        "": [st.Page(home, title="Home", icon=":material/home:", default=True), DRAFT],
        "Analysis": list(analysis_pages.values()),
        "Leagues": [
            st.Page("views/league_admin.py", title="League settings", icon=":material/tune:",
                    url_path="league"),
            st.Page("views/register.py", title="Register a league", icon=":material/add:",
                    url_path="register"),
            JOIN,
            PRIVACY,
        ],
    }
)  # fmt: skip

# Sidebar: which league, who's signed in, and the open league's data freshness.
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
