"""Builds the espn_api League object from env vars.

LEAGUE_ID/SEASON/ESPN_S2/SWID are read from the environment rather than .env
directly -- locally python-dotenv populates them before this runs; in Cloud Run
they're injected via --set-env-vars and --set-secrets.
"""

import os

from espn_api.basketball import League


def build_league() -> League:
    return League(
        league_id=int(os.environ["LEAGUE_ID"]),
        year=int(os.environ["SEASON"]),
        espn_s2=os.environ["ESPN_S2"],
        swid=os.environ["SWID"],
    )
