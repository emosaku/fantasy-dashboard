"""Cached glue between the BigQuery views and app/analysis for the pages that use
the z-score foundation (Roster Strength's Category rankings, Trade Analyzer).

Everything is keyed on plain values (stat window, delta, overrides as a tuple), so
Streamlit caches each combination for an hour like the view reads it's built on.
"""

import pandas as pd
import streamlit as st

import queries
from analysis.pool import empty_slot_z, player_matrix, team_totals
from analysis.trades import SearchTooLarge, build_offers, deals_for_target, find_trades
from analysis.weights import compute_weights

STAT_WINDOWS = {
    "blended": "Blended",
    "projected": "Projected",
    "season": "Season",
    "last_7": "Last 7",
    "last_15": "Last 15",
    "last_30": "Last 30",
}


def available_windows() -> list[str]:
    have = set(queries.player_z()["stat_window"])
    return [w for w in STAT_WINDOWS if w in have]


@st.cache_data(ttl=3600, show_spinner=False)
def league(window: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(players, team totals) for one stat window."""
    z = queries.player_z()
    players = player_matrix(z.loc[z["stat_window"] == window])
    return players, team_totals(players)


@st.cache_data(ttl=3600, show_spinner=False)
def weights_by_team(window: str, me: int, delta: float, overrides: tuple) -> dict:
    """Every team's weights; only `me` gets the user's overrides."""
    _, totals = league(window)
    return {
        t: compute_weights(totals, t, delta, dict(overrides) if t == me else None)
        for t in totals.index
    }


@st.cache_data(ttl=3600, show_spinner="Searching every trade...")
def all_trades(window: str, me: int, delta: float, overrides: tuple) -> pd.DataFrame:
    players, totals = league(window)
    return find_trades(players, totals, me, weights_by_team(window, me, delta, overrides), top=5000)


@st.cache_data(ttl=3600, max_entries=100, show_spinner="Building trades for this player...")
def target_trades(
    window: str, me: int, target: int, delta: float, overrides: tuple
) -> pd.DataFrame:
    players, totals = league(window)
    weights = weights_by_team(window, me, delta, overrides)
    return deals_for_target(players, totals, me, target, weights)


def team_names() -> pd.Series:
    return queries.teams().set_index("team_id")["team_name"].sort_values()


@st.cache_data(ttl=3600, show_spinner=False)
def empty_slot(window: str) -> pd.Series:
    """What an empty roster spot is worth per category (z) in this window. Blended
    mixes season and projected per player, so its empty spot is the average of the
    two windows' (whichever exist)."""
    z = queries.player_z()
    raw = ["season", "projected"] if window == "blended" else [window]
    found = [
        empty_slot_z(z.loc[z["stat_window"] == w]) for w in raw if (z["stat_window"] == w).any()
    ]
    return pd.concat(found, axis=1).mean(axis=1) if found else pd.Series(dtype=float)


@st.cache_data(ttl=3600, max_entries=200, show_spinner="Searching your trade block...")
def offers(
    window: str,
    me: int,
    block: tuple,
    targets: tuple,
    delta: float,
    overrides: tuple,
    max_give: int,
    max_get: int,
    acceptance: str,
    exclude_injured: bool,
    allow_uneven: bool,
) -> tuple[pd.DataFrame | None, str | None]:
    """Offer Builder's search. (deals, problem) -- problem is SearchTooLarge's
    message (too many deals to check) when the search was too big to run, else
    None. Cached by every input, so re-expanding a row never reruns the search."""
    players, totals = league(window)
    weights = weights_by_team(window, me, delta, overrides)
    try:
        deals = build_offers(
            players, totals, me, list(block), list(targets), weights,
            max_give=max_give, max_get=max_get, acceptance=acceptance,
            exclude_injured=exclude_injured, allow_uneven=allow_uneven,
        )  # fmt: skip
        return deals, None
    except SearchTooLarge as error:
        return None, str(error)
