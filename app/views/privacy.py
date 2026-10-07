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
  matchup results, transactions and player stats.
- **For a private league only: one manager's ESPN login** (two browser cookies,
  `espn_s2` and `SWID`), given by the commissioner who connected the league, with their
  consent. It's used for one thing: reading that league's data once a day (or when
  someone presses Refresh). It's kept in Google Cloud Secret Manager, encrypted, where
  only League Lab's daily data pull can read it -- the website can save or delete it
  but can't read it back, and it's never shown, logged or shared.

**What it doesn't do**

- Share or sell any of it, or use it for advertising.
- Use cookies beyond the one that keeps you signed in.
- Post anything to ESPN or change your league. It only reads -- with a saved login too.

**Where it lives.** Google Cloud (United States). Data is refreshed daily while a
league is in use; a league nobody opens for 14 days stops being refreshed.

**Deleting it.** A league's commissioner can remove a saved ESPN login at any time
from League settings (it's deleted at once), or delete the league: its saved login is
deleted at once, and every stored row and membership within minutes. Signing out of
ESPN on that browser usually makes a saved login stop working too. To have your own
account record removed, email the address on the Google sign-in screen.

League Lab is not affiliated with, endorsed by or sponsored by ESPN or the NBA.
"""
)
