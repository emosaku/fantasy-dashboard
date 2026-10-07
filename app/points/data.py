"""Cached glue between the BigQuery reads and the points engine, for the points
pages. Everything is keyed on plain values (league, data version, stat window, the
day), so Streamlit caches each combination like the reads beneath.

The engine's Setup holds a cache of simulated lineups, so it's kept as a shared
resource (one per league, version, window and day) rather than copied per call.
"""

import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import queries
from points import model, trades
from trade import wide_lines

INFO = ["player_name", "position", "pro_team", "team_id", "lineup_slot", "injury_status",
        "expected_return_date", "eligible_slots", "is_free_agent", "is_ir"]  # fmt: skip


def today() -> dt.date:
    """Today in US Eastern time, the NBA's calendar."""
    return dt.datetime.now(ZoneInfo("America/New_York")).date()


def available_windows(league_id: int, version: str) -> list[str]:
    have = set(queries.player_points(league_id, version)["stat_window"])
    if not have:
        return []
    blended = {"season", "projected"} & have
    return [w for w in model.WINDOWS if w in have or (w == "blended" and blended)]


@st.cache_data(ttl=6 * 3600, max_entries=200, show_spinner=False)
def players(league_id: int, version: str, window: str) -> pd.DataFrame:
    """One row per pool player: who and where he is, FP/G in `window` (fpg) and in
    every window (fp_<window>, games_<window>)."""
    pool = queries.player_pool(league_id, version)
    info = pool.drop_duplicates("player_id").set_index("player_id")
    info = info[[c for c in INFO if c in info]]
    wide = model.fp_wide(queries.player_points(league_id, version))
    out = info.join(wide, how="left")
    out["fpg"] = model.fp_per_game(out, window) if not wide.empty else 0.0
    out["team_id"] = out["team_id"].astype("float64")
    return out


@st.cache_data(ttl=6 * 3600, max_entries=200, show_spinner=False)
def stat_lines(league_id: int, version: str, window: str) -> pd.DataFrame:
    """Per-game stat lines, one row per player (index player_id). Blended uses season
    averages once a player has them, ESPN's projection before."""
    pool = queries.player_pool(league_id, version)
    if window == "blended":
        has_season = set(pool.loc[pool["stat_window"] == "season", "player_id"])
        rows = pool.loc[
            (pool["stat_window"] == "season")
            | ((pool["stat_window"] == "projected") & ~pool["player_id"].isin(has_season))
        ]
    else:
        rows = pool.loc[pool["stat_window"] == window]
    return wide_lines(rows).set_index("player_id")


@st.cache_data(ttl=6 * 3600, max_entries=50, show_spinner=False)
def results(league_id: int, version: str, current_week: int) -> pd.DataFrame:
    """Finished matchups with each side's result."""
    return model.played_results(queries.matchup_scores(league_id, version), current_week)


@st.cache_resource(max_entries=30, show_spinner="Simulating every team's lineups...")
def setup(league_id: int, version: str, window: str, current_week: int, last_week: int,
          slots: tuple, bench: int, day: dt.date) -> trades.Setup:  # fmt: skip
    """The engine for one league and stat window, as of `day`."""
    return trades.build(
        players(league_id, version, window),
        queries.pro_schedule(league_id, version),
        dict(slots),
        bench,
        current_week,
        last_week,
        day,
        results(league_id, version, current_week),
    )


def for_context(ctx, window: str) -> trades.Setup:
    return setup(*search_key(ctx, window))


def share_of_week_left(schedule: pd.DataFrame, week: int, day: dt.date) -> float:
    """The share of this week's NBA game days still to come (today included)."""
    days = schedule.loc[schedule["matchup_period"] == week, "game_date"]
    days = pd.to_datetime(days).dt.date.unique()
    if not len(days):
        return 0.0
    return sum(d >= day for d in days) / len(days)


def fmt_points(value) -> str:
    return "–" if value is None or pd.isna(value) else f"{value:,.1f}"


# --- Cached searches: plain-value keys, the Setup rebuilt from the same keys ----------


def search_key(ctx, window: str) -> tuple:
    return (ctx.league_id, ctx.version, window, ctx.current_week, ctx.last_week,
            ctx.lineup_slots, int(ctx.doc.get("bench_slots") or 0), today())  # fmt: skip


@st.cache_data(ttl=3600, max_entries=50, show_spinner="Searching every trade...")
def find_trades(key: tuple, me: int) -> pd.DataFrame:
    return trades.find_trades(setup(*key), me)


@st.cache_data(ttl=3600, max_entries=50, show_spinner="Ranking free agents...")
def waiver_moves(key: tuple, me: int) -> pd.DataFrame:
    return trades.waiver_moves(setup(*key), me)


@st.cache_data(ttl=3600, max_entries=100, show_spinner="Building deals for him...")
def deals_for_target(key: tuple, me: int, target: int, max_size: int) -> pd.DataFrame:
    return trades.deals_for_target(setup(*key), me, target, max_size)


@st.cache_data(ttl=3600, max_entries=100, show_spinner="Searching offers...")
def build_offers(key: tuple, me: int, block: tuple, targets: tuple, max_give: int,
                 max_get: int, acceptance: str, exclude_injured: bool,
                 uneven: bool) -> tuple[pd.DataFrame | None, str | None]:  # fmt: skip
    try:
        deals = trades.build_offers(setup(*key), me, list(block), list(targets), max_give,
                                    max_get, acceptance, exclude_injured, uneven)  # fmt: skip
        return deals, None
    except trades.SearchTooLarge as error:
        return None, str(error)


@st.cache_data(ttl=3600, max_entries=200, show_spinner=False)
def mock_trade(key: tuple, me: int, them: int | None, give: tuple, get: tuple, my_add: tuple,
               my_drop: tuple, their_add: tuple, their_drop: tuple) -> dict:  # fmt: skip
    return trades.mock(setup(*key), me, them, give, get, my_add, my_drop, their_add, their_drop)
