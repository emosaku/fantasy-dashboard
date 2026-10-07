"""Join a league through its invite link (/join?code=...), or by pasting the link or
code. You pick your team; a team can only be claimed once."""

import streamlit as st

import league
import tenancy

st.title("Join a league")
user = league.current_user()
if user is None:
    st.write("Sign in first, then open the invite link again.")
    if league.auth_configured() and st.button("Sign in with Google", type="primary"):
        league.sign_in()
    st.stop()

if "joined" in st.session_state:
    st.success(f"You've joined **{st.session_state.pop('joined')}**. Pick a page on the left.")
    st.stop()

pasted = st.text_input(
    "Invite link or code", value=st.query_params.get("code", ""), placeholder="Paste it here"
)
code = pasted.strip().split("code=")[-1].split("&")[0]
if not code:
    st.stop()

target = tenancy.league_by_invite(league.db(), code)
if target is None:
    st.error(
        "That invite isn't valid. It may have been replaced: ask the commissioner for a new one."
    )
    st.stop()

name = target.get("league_name") or f"League {target['league_id']}"
if any(m["league_id"] == target["league_id"] for m in league.my_memberships()):
    st.info(f"You're already in **{name}**.")
    league.switch_to(target["league_id"])
    st.stop()

teams = {int(t["team_id"]): t["team_name"] for t in target.get("teams", [])}
if not teams:
    st.info(f"**{name}** is still loading its first data. Try again in a few minutes.")
    st.stop()
taken = tenancy.claimed_teams(league.db(), target["league_id"])
options = [None, *sorted((t for t in teams if t not in taken), key=lambda t: teams[t].lower())]

st.subheader(name)
with st.form("join"):
    team = st.selectbox(
        "Your team",
        options,
        format_func=lambda t: "I don't have a team (just looking)" if t is None else teams[t],
        help="Teams someone has already claimed aren't listed.",
    )
    submitted = st.form_submit_button("Join league", type="primary")
if submitted:
    try:
        tenancy.join(league.db(), target, user, team, league.now())
    except tenancy.TenancyError as error:
        st.error(str(error))
        st.stop()
    league.forget_league_cache()
    league.switch_to(target["league_id"])
    st.session_state["joined"] = name
    st.query_params.clear()
    st.rerun()
