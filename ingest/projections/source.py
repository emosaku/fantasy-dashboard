"""BallDontLie ALL-STAR: the stats source behind our projections and stat windows
(docs/whopDocs/projections.md).

A polite client: every request waits its turn under the plan's 60 requests a minute,
and backs off on rate limits and server errors. The key lives in Secret Manager
(`balldontlie-api-key`), never in code or env files.

What it reads, ALL-STAR only:
* /v1/stats -- every player's line in every regular-season game (min "00" = didn't play)
* /v1/players -- names, team, position, draft year (there are no birth dates)
* /v1/player_injuries -- current injury status

BallDontLie names a season by the year it starts (2025 = 2025-26); League Lab by the
year it ends (2026 = 2025-26). Everything here takes and returns League Lab's.
"""

import datetime as dt
import random
import time

import pandas as pd
import requests

BASE = "https://api.balldontlie.io/v1"
SECRET = "balldontlie-api-key"
PER_PAGE = 100
MIN_INTERVAL = 1.05  # seconds between requests: just under 60 a minute
RETRIES = 5
BACKOFF_SECONDS = 5.0
GAME_COLUMNS = ["min", "pts", "reb", "oreb", "dreb", "ast", "stl", "blk", "tov", "fgm", "fga",
                "fg3m", "fg3a", "ftm", "fta"]  # fmt: skip


def api_key(project: str) -> str:
    from google.cloud import secretmanager

    name = f"projects/{project}/secrets/{SECRET}/versions/latest"
    return (
        secretmanager.SecretManagerServiceClient()
        .access_secret_version(name=name)
        .payload.data.decode()
    )


def to_bdl(season: int) -> int:
    return season - 1


def to_league_lab(bdl_season: int) -> int:
    return bdl_season + 1


class Client:
    def __init__(self, key: str, session: requests.Session | None = None, sleep=time.sleep,
                 clock=time.monotonic):  # fmt: skip
        self.session = session or requests.Session()
        self.session.headers["Authorization"] = key
        self.sleep, self.clock = sleep, clock
        self.last = None

    def _get(self, path: str, params: dict) -> dict:
        for attempt in range(RETRIES + 1):
            if self.last is not None:
                wait = MIN_INTERVAL - (self.clock() - self.last)
                if wait > 0:
                    self.sleep(wait)
            self.last = self.clock()
            try:
                response = self.session.get(f"{BASE}/{path}", params=params, timeout=60)
                if response.status_code == 429 or response.status_code >= 500:
                    raise requests.HTTPError(response=response)
                response.raise_for_status()
                return response.json()
            except (requests.HTTPError, requests.ConnectionError, requests.Timeout) as error:
                status = getattr(getattr(error, "response", None), "status_code", None)
                retryable = status is None or status == 429 or status >= 500
                if attempt == RETRIES or not retryable:
                    raise
                self.sleep(BACKOFF_SECONDS * 2**attempt + random.uniform(0, 1))
        raise AssertionError("unreachable")

    def pages(self, path: str, params: dict):
        """Every record of a cursor-paginated endpoint."""
        cursor = None
        while True:
            page = self._get(
                path, params | {"per_page": PER_PAGE} | ({"cursor": cursor} if cursor else {})
            )
            yield from page.get("data", [])
            cursor = (page.get("meta") or {}).get("next_cursor")
            if not cursor:
                return

    def game_stats(self, season: int, start: dt.date | None = None, end: dt.date | None = None):
        """Raw stat rows for one season's regular-season games (optionally a date range)."""
        params = {"seasons[]": to_bdl(season), "season_type": "regular"}
        if start:
            params["start_date"] = start.isoformat()
        if end:
            params["end_date"] = end.isoformat()
        return list(self.pages("stats", params))

    def players(self):
        return list(self.pages("players", {}))

    def injuries(self):
        return list(self.pages("player_injuries", {}))


def minutes(value) -> float:
    """BallDontLie's minutes ("30", "00", sometimes "30:12") as a number."""
    if value in (None, ""):
        return 0.0
    text = str(value)
    if ":" in text:
        whole, seconds = text.split(":", 1)
        return int(whole or 0) + int(seconds or 0) / 60
    return float(text)


def game_rows(records: list[dict], ingested_at: dt.datetime) -> pd.DataFrame:
    """Raw /stats rows -> nba_player_games rows (League Lab seasons, BallDontLie columns)."""
    rows = []
    for r in records:
        game = r.get("game") or {}
        rows.append(
            {
                "player_id": int(r["player"]["id"]),
                "game_id": int(game["id"]),
                "season": to_league_lab(int(game["season"])),
                "game_date": dt.date.fromisoformat(str(game["date"])[:10]),
                "team": (r.get("team") or {}).get("abbreviation"),
                "min": minutes(r.get("min")),
                **{c: float(r.get("turnover" if c == "tov" else c) or 0) for c in GAME_COLUMNS[1:]},
                "ingested_at": ingested_at,
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    # a re-sent page can repeat a row; one per player per game
    return frame.drop_duplicates(["player_id", "game_id"], keep="last").reset_index(drop=True)


def player_rows(records: list[dict], ingested_at: dt.datetime) -> pd.DataFrame:
    """Raw /players rows -> nba_players rows; birth_date and espn_player_id are filled
    in later (matching), so they start empty."""
    return pd.DataFrame(
        [
            {
                "player_id": int(r["id"]),
                "player_name": f"{r.get('first_name', '')} {r.get('last_name', '')}".strip(),
                "team": (r.get("team") or {}).get("abbreviation"),
                "position": r.get("position") or None,
                "draft_year": r.get("draft_year"),
                "birth_date": None,
                "espn_player_id": None,
                "ingested_at": ingested_at,
            }
            for r in records
        ]
    )
