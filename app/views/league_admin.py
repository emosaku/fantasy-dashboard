"""League settings: your team in the open league, and for its commissioner the
invite link, the member list, a private league's ESPN login (replace or remove) and
the delete button."""

from urllib.parse import urlsplit

import streamlit as st

import espn_login
import league
import onboarding
import refresh
import settings
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

# --- ESPN login (private leagues, or public ones whose transactions need it) -----------
if ctx.doc.get("credentials", "public") != "public" or ctx.doc.get("activity_needs_login"):
    st.subheader("ESPN login")
    saved = ctx.doc.get("credentials", "").startswith("secret:")
    if not saved and ctx.doc.get("activity_needs_login"):
        st.caption(
            "ESPN shares this league's standings, rosters and stats publicly, but only "
            "shares its transactions with a manager's login. Connect one to load them."
        )
    if ctx.doc.get("status") == "needs_login":
        st.warning(ctx.doc.get("error") or "This league needs a new ESPN login.")
    elif saved:
        st.caption(
            "This private league is read with a manager's ESPN login, saved so that only "
            "the daily data pull can read it (this page can replace or remove it, never "
            "show it). ESPN logins expire; if one does, you'll be asked for a new one here."
        )
    with st.form("login", clear_on_submit=True):
        st.markdown("**Connect a new login** (the steps are on the Register page)")
        espn_s2 = st.text_input("espn_s2", type="password")
        swid = st.text_input("SWID", type="password")
        replace = st.form_submit_button("Save new login")
    if replace:
        try:
            cookies = onboarding.clean_cookies(espn_s2, swid)
            with st.spinner("Checking the login with ESPN..."):
                onboarding.preview(ctx.league_id, ctx.season, cookies=cookies)
            credentials = espn_login.save(
                espn_login.client(), settings.PROJECT, ctx.league_id, cookies
            )
        except onboarding.CannotRegister as error:
            st.error(str(error))
        else:
            tenancy.set_login(db, ctx.league_id, credentials, league.now())
            try:
                refresh.ingest_league(ctx.league_id)
            except Exception:  # the daily run picks it up anyway
                pass
            league.forget_league_cache()
            st.success("Saved. The league's data is refreshing now.")
        finally:
            espn_s2 = swid = cookies = None  # noqa: F841  (drop the login from memory)
    if saved and st.button(
        "Remove the saved login",
        help="Deletes it at once. The league's data stays but stops refreshing until a "
        "new login is connected.",
    ):
        espn_login.remove(espn_login.client(), settings.PROJECT, ctx.league_id)
        tenancy.remove_login(db, ctx.league_id, league.now())
        league.forget_league_cache()
        st.rerun()

# --- Delete ------------------------------------------------------------------------
st.subheader("Delete this league")
st.caption(
    "Removes the league from League Lab for everyone: all of its stored data, every "
    "membership, the invite link and any saved ESPN login. It can't be undone (you "
    "could register it again)."
)
confirm = st.text_input(f"Type the league id ({ctx.league_id}) to confirm")
if st.button("Delete league", type="primary", disabled=confirm.strip() != str(ctx.league_id)):
    tenancy.mark_deleting(db, ctx.league_id, league.now())
    if ctx.doc.get("credentials", "public").startswith("secret:"):
        espn_login.remove(espn_login.client(), settings.PROJECT, ctx.league_id)  # at once
    try:
        refresh.purge()
    except Exception:  # the next daily run purges it anyway
        pass
    st.session_state.pop("league_id", None)
    league.forget_league_cache()
    st.success("Deleted. Its data is being removed now.")
    st.rerun()
