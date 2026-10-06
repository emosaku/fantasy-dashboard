"""Register a league: paste its ESPN link or id, League Lab checks it's public and
supported (app/onboarding.py), you pick your team, and the first data load starts.
The person who registers a league is its commissioner on League Lab."""

import streamlit as st

import league
import onboarding
import refresh
import settings
import tenancy

st.title("Register a league")
st.caption(
    "Public ESPN fantasy basketball leagues, head-to-head categories (Most Categories or "
    "Each Category). You become the league's commissioner here: you get an invite link "
    "to share, and you can delete the league's data at any time."
)
user = league.current_user()

text = st.text_input(
    "Your ESPN league link or league id",
    placeholder="https://fantasy.espn.com/basketball/league?leagueId=12345678",
)
league_id = tenancy.parse_league_id(text)
if text and league_id is None:
    st.error("That doesn't look like an ESPN league link or id.")
if league_id is None:
    st.stop()


@st.cache_data(ttl=600, show_spinner="Checking the league on ESPN...")
def check(league_id: int, season: int) -> tuple[dict | None, str | None]:
    try:
        return onboarding.preview(league_id, season), None
    except onboarding.CannotRegister as error:
        return None, str(error)


preview, problem = check(league_id, settings.SEASON)
if problem:
    st.error(problem)
    st.stop()

existing = tenancy.get_league(league.db(), league_id)
if existing and existing.get("status") != "deleting":
    st.info("This league is already on League Lab. Ask its commissioner for the invite link.")
    st.stop()

scoring = "Each Category" if preview["scoring_type"] == "H2H_EACH_CATEGORY" else "Most Categories"
st.success(f"**{preview['league_name']}** can be added.")
st.markdown(
    f"{len(preview['teams'])} teams · {scoring} · categories: "
    + ", ".join(
        c["category"] + (" (lower wins)" if c["lower_is_better"] else "")
        for c in preview["categories"]
    )
)

team_options = [None, *[t["team_id"] for t in preview["teams"]]]
names = {t["team_id"]: t["team_name"] for t in preview["teams"]}
with st.form("register"):
    team = st.selectbox(
        "Your team",
        team_options,
        format_func=lambda t: "I don't have a team in this league" if t is None else names[t],
    )
    agree = st.checkbox(
        "I'm in this league, and I'm OK with League Lab storing its public data (see Privacy)."
    )
    submitted = st.form_submit_button("Register league", type="primary", disabled=False)

if submitted:
    if not agree:
        st.error("Please confirm first.")
        st.stop()
    try:
        tenancy.register(
            league.db(),
            league_id,
            settings.SEASON,
            user,
            team,
            preview["league_name"],
            league.now(),
            settings.MAX_LEAGUES,
            settings.MAX_LEAGUES_PER_USER,
        )
    except tenancy.TenancyError as error:
        st.error(str(error))
        st.stop()
    try:
        refresh.ingest_league(league_id)
    except Exception:  # the daily run picks it up anyway
        st.warning("Couldn't start the first data load now; it will run tomorrow morning.")
    league.forget_league_cache()
    st.session_state["league_id"] = league_id
    st.success(
        "Registered. The first data load takes a few minutes; then share the invite link "
        "from League settings."
    )
    st.page_link("pages/league_admin.py", label="Open League settings", icon=":material/tune:")
