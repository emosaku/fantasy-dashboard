"""Privacy policy -- reachable signed in or out (linked from the footer and the
Google sign-in consent screen)."""

import streamlit as st

st.title("Privacy")
st.caption("Last updated October 5, 2026")
st.markdown(
    """
League Lab is a free, non-commercial project run by one person. It has no ads and
sells nothing, including your data.

**What it stores**

- **Your Google account's name, email and account id**, when you sign in. Nothing else
  from your Google account: no contacts, files or password.
- **Which leagues you belong to and which team is yours.**
- **Your league's data from ESPN**: settings, teams and managers' names, rosters,
  matchup results, transactions and player stats. League Lab only reads leagues
  that are public on ESPN.

**What it doesn't do**

- Share or sell any of it, or use it for advertising.
- Use cookies beyond the one that keeps you signed in.
- Post anything to ESPN or change your league. It only reads.

**Where it lives.** Google Cloud (United States). Data is refreshed daily while a
league is in use; a league nobody opens for 14 days stops being refreshed.

**Deleting it.** A league's commissioner can delete the league from League settings:
every stored row for that league, and every membership in it, is removed within a
day. To have your own account record removed, email the address on the Google
sign-in screen.

League Lab is not affiliated with, endorsed by or sponsored by ESPN or the NBA.
"""
)
