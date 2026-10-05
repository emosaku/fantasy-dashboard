"""Builds the espn_api League object from env vars.

LEAGUE_ID/SEASON/ESPN_S2/SWID are read from the environment rather than .env
directly -- locally python-dotenv populates them before this runs; in Cloud Run
they're injected via --set-env-vars and --set-secrets.
"""

import json
import os

import requests
from espn_api.basketball import League


def build_league() -> League:
    return League(
        league_id=int(os.environ["LEAGUE_ID"]),
        year=int(os.environ["SEASON"]),
        espn_s2=os.environ["ESPN_S2"],
        swid=os.environ["SWID"],
    )


LEAGUE_URL = (
    "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{season}"
    "/segments/0/leagues/{league_id}"
)


def fetch_player_info(season: int, player_ids: list[int], batch_size: int = 100) -> list[dict]:
    """Raw ESPN player records for these players in one season, from the league's
    kona_player_info view: injury fields, the season outlook, and season-total
    actual stats (GP is stat "42").

    Any past season works, not just the league's current one -- that's how the
    games-played history is read -- so this goes straight to the endpoint instead of
    through espn_api, whose League object is tied to a single season.
    """
    url = LEAGUE_URL.format(season=season, league_id=os.environ["LEAGUE_ID"])
    cookies = {"espn_s2": os.environ["ESPN_S2"], "SWID": os.environ["SWID"]}
    records = []
    for start in range(0, len(player_ids), batch_size):
        batch = list(player_ids[start : start + batch_size])
        filters = {
            "players": {
                # No "limit": ESPN rejects one unless it comes with a sort, and the
                # id filter already bounds the result to this batch.
                "filterIds": {"value": batch},
                "filterStatsForSourceIds": {"value": [0]},  # actual stats, not projections
                "filterStatsForSplitTypeIds": {"value": [0]},  # season totals
            }
        }
        response = requests.get(
            url,
            params={"view": "kona_player_info"},
            headers={"x-fantasy-filter": json.dumps(filters)},
            cookies=cookies,
            timeout=60,
        )
        response.raise_for_status()
        records.extend(entry["player"] for entry in response.json().get("players", []))
    return records
