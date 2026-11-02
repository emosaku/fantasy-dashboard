"""BallDontLie ALL-STAR: the stats source behind our projections and stat windows
(docs/whopDocs/projections.md).

A polite client: every request waits its turn under the plan's 60 requests a minute,
and backs off on rate limits and server errors. The key lives in Secret Manager
(`balldontlie-api-key`), never in code or env files.

What it reads, ALL-STAR only:
* /v1/stats -- every player's line in every regular-season game (min "00" = didn't play)
* /v1/players -- names, team, position, draft year (there are no birth dates)
* /v1/games -- the season's schedule (games left per team, for the in-season blend)
* /v1/player_injuries -- current injury status (status and return date only: the
  written notes are someone else's reporting and aren't kept)

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
                "fg3m", "fg3a", "ftm", "fta", "pf"]  # fmt: skip


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

    def players(self, ids: list[int] | None = None):
        """Every player, or only these ids (100 per request)."""
        if ids is None:
            return list(self.pages("players", {}))
        ids = sorted(set(ids))
        return [
            p
            for start in range(0, len(ids), PER_PAGE)
            for p in self.pages("players", {"player_ids[]": ids[start : start + PER_PAGE]})
        ]

    def games(self, season: int):
        """The season's regular-season schedule, played and not."""
        return list(self.pages("games", {"seasons[]": to_bdl(season), "postseason": "false"}))

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


def final(game: dict) -> bool:
    """A finished game (a game in progress has partial lines). Older rows without a
    status count as finished."""
    state = game.get("status_state")
    if state:
        return state == "final"
    status = game.get("status")
    return not status or str(status).startswith("Final")


def game_rows(records: list[dict], ingested_at: dt.datetime) -> pd.DataFrame:
    """Raw /stats rows -> nba_player_games rows (League Lab seasons, BallDontLie columns).
    Games not yet finished are left out."""
    rows = []
    for r in records:
        game = r.get("game") or {}
        if not final(game):
            continue
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


def games_left(schedule: list[dict], after: dt.date) -> pd.Series:
    """Games each team still has after `after`, by team abbreviation."""
    teams = [
        (g.get(side) or {}).get("abbreviation")
        for g in schedule
        if dt.date.fromisoformat(str(g["date"])[:10]) > after and not g.get("postseason")
        for side in ("home_team", "visitor_team")
    ]
    return pd.Series(teams, dtype="object").value_counts().rename("games_left")


# BallDontLie's statuses -> the codes League Lab's pages use (ESPN's)
INJURY_STATUS = {
    "Out": "OUT",
    "Doubtful": "DAY_TO_DAY",
    "Questionable": "DAY_TO_DAY",
    "Day-To-Day": "DAY_TO_DAY",
    "Probable": "ACTIVE",
    "Available": "ACTIVE",
}


def injury_rows(records: list[dict], ingested_at: dt.datetime) -> pd.DataFrame:
    """Raw /player_injuries rows -> nba_injuries rows: status and return date only."""
    rows = []
    for r in records:
        returns = r.get("return_date")
        rows.append(
            {
                "player_id": int(r["player"]["id"]),
                "status": INJURY_STATUS.get(r.get("status"), "DAY_TO_DAY"),
                "source_status": r.get("status"),
                "return_date": dt.date.fromisoformat(returns[:10]) if returns else None,
                "ingested_at": ingested_at,
            }
        )
    columns = ["player_id", "status", "source_status", "return_date", "ingested_at"]
    return pd.DataFrame(rows, columns=columns).drop_duplicates("player_id", keep="last")
