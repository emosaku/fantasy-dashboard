"""Everything that talks to ESPN, written to be a polite client.

* Public leagues need no credentials. A league registered with credentials
  (`credentials = "secret:<name>"`, Phase 2) reads its espn_s2/SWID from Secret Manager.
* Every request goes through `polite()`: a short pause before each call, and
  exponential backoff on rate limits, ESPN errors and network failures. Access denied
  (a private league) and missing leagues fail at once -- retrying won't help.
"""

import json
import random
import time

import requests
from espn_api.basketball import League
from espn_api.requests.espn_requests import (
    ESPNAccessDenied,
    ESPNInvalidLeague,
    ESPNUnknownError,
)

LEAGUE_URL = (
    "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{season}"
    "/segments/0/leagues/{league_id}"
)
PAUSE_SECONDS = 0.5
RETRIES = 4
BACKOFF_SECONDS = 4.0


class LeagueNotAccessible(Exception):
    """Private, deleted or wrong league id -- a message for people, not a retry."""


def _retryable(error: Exception) -> bool:
    if isinstance(error, (ESPNAccessDenied, ESPNInvalidLeague, LeagueNotAccessible)):
        return False
    if isinstance(error, requests.HTTPError) and error.response is not None:
        return error.response.status_code == 429 or error.response.status_code >= 500
    return isinstance(error, (ESPNUnknownError, requests.ConnectionError, requests.Timeout))


def polite(call, *, sleep=time.sleep, retries: int = RETRIES, backoff: float = BACKOFF_SECONDS):
    """Run one ESPN call: pause first, back off and retry on transient failures."""
    for attempt in range(retries + 1):
        sleep(PAUSE_SECONDS)
        try:
            return call()
        except Exception as error:
            if attempt == retries or not _retryable(error):
                raise
            sleep(backoff * 2**attempt + random.uniform(0, 1))


def _translate(error: Exception) -> Exception:
    if isinstance(error, ESPNAccessDenied):
        return LeagueNotAccessible(
            "ESPN won't share this league without a login: it's private. League Lab "
            "only supports public leagues for now."
        )
    if isinstance(error, ESPNInvalidLeague):
        return LeagueNotAccessible("ESPN has no basketball league with that id this season.")
    return error


def build_league(league_id: int, season: int, cookies: dict | None = None) -> League:
    cookies = cookies or {}
    try:
        return polite(
            lambda: League(
                league_id=league_id,
                year=season,
                espn_s2=cookies.get("espn_s2"),
                swid=cookies.get("SWID"),
            )
        )
    except Exception as error:
        raise _translate(error) from error


def _get(url: str, params: dict, headers: dict | None, cookies: dict | None) -> dict:
    def call():
        response = requests.get(
            url, params=params, headers=headers or {}, cookies=cookies or {}, timeout=60
        )
        if response.status_code == 401:
            raise LeagueNotAccessible("ESPN refused access to this league.")
        if response.status_code == 404:
            raise LeagueNotAccessible("ESPN has no basketball league with that id this season.")
        response.raise_for_status()
        return response.json()

    return polite(call)


def fetch_settings(league_id: int, season: int, cookies: dict | None = None) -> dict:
    """The league's raw ESPN settings (scoringSettings, scheduleSettings, name ...)."""
    url = LEAGUE_URL.format(season=season, league_id=league_id)
    return _get(url, {"view": "mSettings"}, None, cookies)["settings"]


def fetch_views(league_id: int, season: int, views: list[str], cookies: dict | None = None):
    """The league's raw ESPN document for these views (e.g. mSettings + mTeam)."""
    url = LEAGUE_URL.format(season=season, league_id=league_id)
    return _get(url, {"view": views}, None, cookies)


def fetch_player_info(
    league_id: int,
    season: int,
    player_ids: list[int],
    cookies: dict | None = None,
    batch_size: int = 100,
) -> list[dict]:
    """Raw ESPN player records (injury fields, outlook, season-total actual stats) for
    these players in one season -- any past season too, via that season's league."""
    url = LEAGUE_URL.format(season=season, league_id=league_id)
    records = []
    for start in range(0, len(player_ids), batch_size):
        batch = [int(p) for p in player_ids[start : start + batch_size]]
        filters = {
            "players": {
                # No "limit": ESPN rejects one without a sort; the ids bound it anyway.
                "filterIds": {"value": batch},
                "filterStatsForSourceIds": {"value": [0]},
                "filterStatsForSplitTypeIds": {"value": [0]},
            }
        }
        headers = {"x-fantasy-filter": json.dumps(filters)}
        data = _get(url, {"view": "kona_player_info"}, headers, cookies)
        records.extend(entry["player"] for entry in data.get("players", []))
    return records


DEFAULTS_URL = (
    "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{season}"
    "/segments/0/leaguedefaults/3"
)


def fetch_player_history(season: int, player_ids: list[int], batch_size: int = 100) -> list[dict]:
    """Player records for a past season from ESPN's league-independent player data
    (what its public player pages use): no login, and no need for the league to have
    existed that season."""
    records = []
    for start in range(0, len(player_ids), batch_size):
        batch = [int(p) for p in player_ids[start : start + batch_size]]
        filters = {
            "players": {
                "filterIds": {"value": batch},
                "filterStatsForSourceIds": {"value": [0]},
                "filterStatsForSplitTypeIds": {"value": [0]},
            }
        }
        headers = {"x-fantasy-filter": json.dumps(filters)}
        data = _get(DEFAULTS_URL.format(season=season), {"view": "kona_player_info"}, headers, None)
        records.extend(entry["player"] for entry in data.get("players", []))
    return records


ACTIVITY_TYPES = [178, 180, 179, 239, 181, 244, 188]


def fetch_activity(
    league_id: int,
    season: int,
    newer_than_ms: int = 0,
    cookies: dict | None = None,
    page_size: int = 50,
    max_pages: int = 100,
) -> list[dict]:
    """Activity topics (adds, drops, trades, lineup moves), newest first, stopping at
    the first page that reaches activity already loaded (`newer_than_ms`) -- so a
    daily run usually makes one request. Topics at or before that time are dropped."""
    url = LEAGUE_URL.format(season=season, league_id=league_id) + "/communication/"
    topics = []
    for page in range(max_pages):
        filters = {
            "topics": {
                "filterType": {"value": ["ACTIVITY_TRANSACTIONS"]},
                "limit": page_size,
                "limitPerMessageSet": {"value": 25},
                "offset": page * page_size,
                "sortMessageDate": {"sortPriority": 1, "sortAsc": False},
                "sortFor": {"sortPriority": 2, "sortAsc": False},
                "filterIncludeMessageTypeIds": {"value": ACTIVITY_TYPES},
            }
        }
        headers = {"x-fantasy-filter": json.dumps(filters)}
        batch = _get(url, {"view": "kona_league_communication"}, headers, cookies)
        batch = batch.get("topics", [])
        topics.extend(t for t in batch if t["date"] > newer_than_ms)
        if len(batch) < page_size or any(t["date"] <= newer_than_ms for t in batch):
            break
    return topics


def fetch_draft_pool(league_id: int, season: int, cookies: dict | None = None,
                     size: int = 400, rank_type: str = "STANDARD") -> list[dict]:  # fmt: skip
    """The `size` best players by ESPN's draft rank (STANDARD for points, ROTO for
    categories), rostered or not, as raw records: ADP, auction value, both draft ranks,
    eligible slots, injury, and their projected and past stats. With the league's id,
    ESPN computes each projection's appliedAverage under the league's scoring."""
    url = LEAGUE_URL.format(season=season, league_id=league_id)
    filters = {
        "players": {
            "limit": size,
            "sortDraftRanks": {"sortPriority": 100, "sortAsc": True, "value": rank_type},
            "filterStatsForSourceIds": {"value": [0, 1]},
            "filterStatsForSplitTypeIds": {"value": [0]},
        }
    }
    headers = {"x-fantasy-filter": json.dumps(filters)}
    data = _get(url, {"view": "kona_player_info"}, headers, cookies)
    return [entry["player"] for entry in data.get("players", [])]


def check_public(league_id: int, season: int) -> dict:
    """Registration check: the league's settings if ESPN shares them with no login;
    raises LeagueNotAccessible (with a message for the commissioner) otherwise."""
    try:
        return fetch_settings(league_id, season)
    except LeagueNotAccessible as error:
        if "no basketball league" in str(error):
            raise
        raise LeagueNotAccessible(
            "ESPN won't share this league without a login, so it's private. League Lab "
            "supports public leagues for now: in ESPN, open League > Settings and make "
            "the league viewable to the public, then try again."
        ) from None
