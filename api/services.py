"""The work behind the endpoints for one league, cached in memory by data version the
way the Streamlit wrappers cache it (analyzer.py, points/data.py): a categories
league's players and team totals per stat window, a points league's simulation
engine per window and day. The trade finder's default search is also kept in the
finder cache table, so it's computed once per data load (precompute.py) instead of on
a person's first visit.
"""

import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd
from fastapi import HTTPException

from analysis import trades as cat_trades
from api import engine
from api.store import LRU
from points import model
from points import trades as pts_trades

NBA_TIME = ZoneInfo("America/New_York")
SETUPS = LRU(30)  # points engines are big: keep a few
FRAMES = LRU(200)


def today() -> dt.date:
    """Today in US Eastern time, the NBA's calendar (points/data.today)."""
    return dt.datetime.now(NBA_TIME).date()


class LeagueData:
    """One league's data and engines for one request."""

    def __init__(self, store, ctx):
        self.store, self.ctx = store, ctx

    def table(self, name: str) -> pd.DataFrame:
        return self.store.table(self.ctx.league_id, self.ctx.version, name)

    # --- Stat windows ---
    def windows(self) -> list[str]:
        if self.ctx.is_points:
            return engine.pts_windows(self.table("player_points"))
        return engine.cat_windows(self.table("m_player_z"))

    def window(self, asked: str | None) -> str:
        have = self.windows()
        if not have:
            raise HTTPException(409, "No player data yet.")
        if asked is None:
            return have[0]
        if asked not in have:
            raise HTTPException(422, f"Stat window must be one of: {', '.join(have)}.")
        return asked

    # --- Categories ---
    @staticmethod
    def _cached(key, make):
        found = FRAMES.get(key)
        return found if found is not None else FRAMES.put(key, make())

    def cat_league(self, window: str):
        key = ("cat", self.ctx.league_id, self.ctx.version, window)
        return self._cached(key, lambda: engine.cat_league(self.table("m_player_z"), window))

    def columns(self) -> list[str]:
        return [c.key for c in self.ctx.cats]

    # --- Points ---
    def pts_players(self, window: str) -> pd.DataFrame:
        key = ("pts-players", self.ctx.league_id, self.ctx.version, window)
        return self._cached(
            key,
            lambda: engine.pts_players(
                self.table("m_player_pool"), self.table("player_points"), window
            ),
        )

    def setup(self, window: str, day: dt.date | None = None) -> pts_trades.Setup:
        day = day or today()
        key = (self.ctx.league_id, self.ctx.version, window, day)
        found = SETUPS.get(key)
        if found is None:
            found = SETUPS.put(key, engine.pts_setup(
                self.pts_players(window), self.table("pro_schedule"), self.ctx.lineup_slots,
                self.ctx.bench, self.ctx.current_week, self.ctx.last_week, day,
                self.table("matchup_scores"),
            ))  # fmt: skip
        return found

    def pts_waivers(self, window: str, me: int) -> pd.DataFrame:
        """points.trades.waiver_moves, kept per data version, window, day and team."""
        key = ("pts-waivers", self.ctx.league_id, self.ctx.version, window, today(), me)
        return self._cached(key, lambda: pts_trades.waiver_moves(self.setup(window), me))

    def names(self, frame: pd.DataFrame | None = None) -> pd.Series:
        if frame is not None and "player_name" in frame:
            return frame["player_name"]
        pool = self.table("m_player_pool").drop_duplicates("player_id")
        return pool.set_index("player_id")["player_name"]

    # --- The trade finder ---
    def finder(self, me: int, window: str, delta: float = engine.DEFAULT_DELTA,
               overrides: dict | None = None, now=None) -> list[dict]:  # fmt: skip
        """Win-win trades for `me`. The default search (default swing size, no tier
        overrides) comes from the finder cache when this data load has one, and is
        stored there when it's computed; any other search is computed fresh."""
        default = delta == engine.DEFAULT_DELTA and not overrides
        if default:
            cached = self.store.finder_get(self.ctx.league_id, me, window, self.ctx.version)
            if cached is not None:
                return cached
        rows = self._find(me, window, delta, overrides)
        if default:
            self.store.finder_put(self.ctx.league_id, me, window, self.ctx.version, rows,
                                  now or dt.datetime.now(dt.UTC))  # fmt: skip
        return rows

    def _find(self, me: int, window: str, delta: float, overrides: dict | None) -> list[dict]:
        if self.ctx.is_points:
            setup = self.setup(window)
            deals = pts_trades.find_trades(setup, me)
            return [self.pts_deal(setup.players, d) for _, d in deals.iterrows()]
        players, totals = self.cat_league(window)
        if me not in totals.index:
            return []
        weights = engine.cat_weights(totals, me, delta, overrides)
        deals = engine.cat_finder(players, totals, me, weights)
        return [self.cat_deal(players, d) for _, d in deals.iterrows()]

    def cat_deal(self, players: pd.DataFrame, d) -> dict:
        cols = self.columns()
        names = players["player_name"]
        # analysis.trades rows: give_ids / get_ids are tuples; drops and adds one id or None
        source = {"give": "give_ids", "get": "get_ids", "my_drop": "my_drop_id",
                  "their_drop": "their_drop_id", "my_add": "my_add_id",
                  "their_add": "their_add_id"}  # fmt: skip
        ids = {k: [int(p) for p in cat_trades.as_ids(d[col])] for k, col in source.items()}
        mine = engine.cat_deltas(d, cols)
        status = engine.verdict(float(d["dE_me"]), float(d["dE_them"]), bool(d["lopsided"]))
        return {
            "partner_id": int(d["partner_id"]),
            "partner": self.ctx.teams.get(int(d["partner_id"])),
            **{f"{k}_ids": v for k, v in ids.items()},
            **{k: [names.get(p, str(p)) for p in v] for k, v in ids.items()},
            "my_change": float(d["dE_me"]),
            "their_change": float(d["dE_them"]),
            "change_unit": "expected category wins a week",
            "categories": mine,
            "lopsided": bool(d["lopsided"]),
            "verdict": status,
            "reason": engine.explain(mine),
        }

    def pts_deal(self, players: pd.DataFrame, d) -> dict:
        ids = {
            k: [int(p) for p in (d[f"{k}_ids"] or ())]
            for k in ("give", "get", "my_drop", "their_drop", "my_add", "their_add")
        }
        names = players["player_name"]
        text = engine.pts_deal_text(players, d)
        return {
            "partner_id": int(d["partner_id"]),
            "partner": self.ctx.teams.get(int(d["partner_id"])),
            **{f"{k}_ids": v for k, v in ids.items()},
            **{k: [names.get(p, str(p)) for p in v] for k, v in ids.items()},
            "my_change": float(d["dE_me"]),
            "their_change": float(d["dE_them"]),
            "change_unit": "expected wins a week",
            "my_points_change": float(d["dmu_me"]),
            "their_points_change": float(d["dmu_them"]),
            "lopsided": bool(d["lopsided"]),
            "verdict": engine.verdict(
                float(d["dE_me"]), float(d["dE_them"]), bool(d["lopsided"])
            ),  # fmt: skip
            "reason": text["reason"],
            "pitch": text["pitch"],
        }


def statuses() -> dict:
    """The verdict words (shared by both engines' rules)."""
    return {"win_win": cat_trades.WIN_WIN, "they_say_no": cat_trades.THEY_SAY_NO,
            "costs_you": cat_trades.COSTS_YOU}  # fmt: skip


def unavailable(status) -> bool:
    return status in model.UNAVAILABLE
