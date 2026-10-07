"""Register a league: paste its ESPN link or id, League Lab checks it (app/
onboarding.py), and the first data load starts. A public league needs nothing else;
you pick your team. A private league needs a manager's ESPN login (two browser
cookies): it's checked against ESPN, must belong to someone in the league (which also
tells us your team), and is saved write-only (app/espn_login.py). The person who
registers a league is its commissioner on League Lab."""

import streamlit as st

import espn_login
import league
import onboarding
import refresh
import settings
import tenancy

st.title("Register a league")
st.caption(
    "ESPN fantasy basketball leagues, head-to-head categories (Most Categories or Each "
    "Category), public or private. You become the league's commissioner here: you get an "
    "invite link to share, and you can delete the league's data at any time."
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
def check(league_id: int, season: int) -> tuple[dict | None, str | None, bool]:
    """(preview, problem, private) -- without a login, so it's safe to cache."""
    try:
        return onboarding.preview(league_id, season), None, False
    except onboarding.NeedsLogin as error:
        return None, str(error), True
    except onboarding.CannotRegister as error:
        return None, str(error), False


preview, problem, private = check(league_id, settings.SEASON)
if problem and not private:
    st.error(problem)
    st.stop()

existing = tenancy.get_league(league.db(), league_id)
if existing and existing.get("status") != "deleting":
    st.info("This league is already on League Lab. Ask its commissioner for the invite link.")
    st.stop()


def start_first_load() -> None:
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
    st.page_link("views/league_admin.py", label="Open League settings", icon=":material/tune:")


if private:
    st.warning(problem)
    with st.expander("How to find your ESPN login (on a computer)", expanded=True):
        st.markdown(
            "1. On a computer, sign in at **fantasy.espn.com** and open your league.\n"
            "2. Open the browser's developer tools: **Chrome / Edge**: right-click the page "
            "> Inspect > **Application** tab > Cookies > `https://fantasy.espn.com`. "
            "**Safari**: Settings > Advanced > show Develop menu, then Develop > Show Web "
            "Inspector > **Storage** > Cookies. **Firefox**: right-click > Inspect > "
            "**Storage** > Cookies.\n"
            "3. Copy the **Value** of `espn_s2` (a long code) and of `SWID` (looks like "
            "`{ABCD1234-...}`) into the boxes below.\n\n"
            "These two cookies act as your ESPN login, so treat them like a password. "
            "League Lab only uses them to *read* this league, never to change anything. "
            "They're saved so that only the daily data pull can read them, and you can "
            "remove them any time (League settings) -- deleting the league removes them too."
        )
    with st.form("private", clear_on_submit=True):
        espn_s2 = st.text_input("espn_s2", type="password")
        swid = st.text_input("SWID", type="password")
        agree = st.checkbox(
            "I'm a manager in this league, and I agree to League Lab saving this ESPN login "
            "to read the league's data (see Privacy)."
        )
        submitted = st.form_submit_button("Connect and register", type="primary")
    if not submitted:
        st.stop()
    if not agree:
        st.error("Please confirm first.")
        st.stop()
    user_db = league.db()
    try:
        cookies = onboarding.clean_cookies(espn_s2, swid)
        tenancy.check_can_register(
            user_db, league_id, user, settings.MAX_LEAGUES, settings.MAX_LEAGUES_PER_USER
        )
        with st.spinner("Checking the login with ESPN..."):
            found = onboarding.preview(league_id, settings.SEASON, cookies=cookies)
        secrets = espn_login.client()
        credentials = espn_login.save(secrets, settings.PROJECT, league_id, cookies)
    except (onboarding.CannotRegister, tenancy.TenancyError) as error:
        st.error(str(error))
        st.stop()
    finally:
        espn_s2 = swid = cookies = None  # noqa: F841  (drop the login from memory)
    try:
        tenancy.register(
            user_db,
            league_id,
            settings.SEASON,
            user,
            found["my_team"],
            found["league_name"],
            league.now(),
            settings.MAX_LEAGUES,
            settings.MAX_LEAGUES_PER_USER,
            credentials=credentials,
        )
    except tenancy.TenancyError as error:
        espn_login.remove(secrets, settings.PROJECT, league_id)
        st.error(str(error))
        st.stop()
    team = next((t["team_name"] for t in found["teams"] if t["team_id"] == found["my_team"]), None)
    st.info(f"Connected **{found['league_name']}**" + (f" as **{team}**." if team else "."))
    start_first_load()
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
    start_first_load()
