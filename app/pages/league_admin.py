"""League settings: your team in the open league, and for its commissioner the
invite link, the member list and the delete button."""

from urllib.parse import urlsplit

import streamlit as st

import league
import refresh
import tenancy

st.title("League settings")
ctx = league.current()
db = league.db()
user = league.current_user()
st.subheader(ctx.name)

# --- Your team ---------------------------------------------------------------------
team_options = [None, *ctx.team_names.index]
taken = tenancy.claimed_teams(db, ctx.league_id)
free = [t for t in team_options if t is None or t == ctx.my_team or t not in taken]
with st.form("my-team"):
    team = st.selectbox(
        "Your team",
        free,
        index=free.index(ctx.my_team) if ctx.my_team in free else 0,
        format_func=lambda t: "No team (just looking)" if t is None else ctx.team_names[t],
        help="The Trade Analyzer works for your own team. Teams others have claimed aren't listed.",
    )
    if st.form_submit_button("Save"):
        try:
            tenancy.set_team(db, ctx.league_id, user["uid"], team)
        except tenancy.TenancyError as error:
            st.error(str(error))
        else:
            league.forget_league_cache()
            st.rerun()

if not ctx.is_commissioner:
    st.caption("Only the league's commissioner on League Lab can invite people or delete it.")
    st.stop()

# --- Invite link -------------------------------------------------------------------
st.subheader("Invite link")
parts = urlsplit(st.context.url or "")
base = f"{parts.scheme}://{parts.netloc}" if parts.netloc else ""
code = ctx.doc.get("invite_code")
if code:
    st.code(f"{base}/join?code={code}", language=None)
    st.caption(
        "Anyone with this link can join after signing in. Replace it to stop the old one working."
    )
if st.button("Replace invite link" if code else "Create invite link"):
    tenancy.rotate_invite(db, ctx.league_id)
    league.forget_league_cache()
    st.rerun()

# --- Members -----------------------------------------------------------------------
st.subheader("Members")
for member in sorted(tenancy.members(db, ctx.league_id), key=lambda m: m.get("name", "")):
    c1, c2 = st.columns([4, 1])
    team_id = member.get("team_id")
    team_label = ctx.team_names.get(team_id, "no team") if team_id is not None else "no team"
    c1.markdown(f"**{member.get('name')}** · {team_label} · {member.get('role')}")
    if member["uid"] != user["uid"] and c2.button("Remove", key=f"rm-{member['uid']}"):
        tenancy.remove_member(db, ctx.league_id, member["uid"])
        st.rerun()

# --- Delete ------------------------------------------------------------------------
st.subheader("Delete this league")
st.caption(
    "Removes the league from League Lab for everyone: all of its stored data, every "
    "membership and the invite link. It can't be undone (you could register it again)."
)
confirm = st.text_input(f"Type the league id ({ctx.league_id}) to confirm")
if st.button("Delete league", type="primary", disabled=confirm.strip() != str(ctx.league_id)):
    tenancy.mark_deleting(db, ctx.league_id, league.now())
    try:
        refresh.purge()
    except Exception:  # the next daily run purges it anyway
        pass
    st.session_state.pop("league_id", None)
    league.forget_league_cache()
    st.success("Deleted. Its data is being removed now.")
    st.rerun()
