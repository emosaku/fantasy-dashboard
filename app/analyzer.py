"""Cached glue between the m_player_z table and app/analysis for the pages that use
the z-score foundation (Roster Strength's Category rankings, Trade Analyzer,
Player Rankings).

Everything is keyed on plain values (league, data version, stat window, delta,
overrides as a tuple), so Streamlit caches each combination like the reads beneath.
"""

import pandas as pd
import streamlit as st

import queries
from analysis.pool import empty_slot_z, player_matrix, team_totals
from analysis.trades import deals_for_target, find_trades
from analysis.weights import compute_weights

STAT_WINDOWS = {
    "blended": "Blended",
    "projected": "Projected",
    "season": "Season",
    "last_7": "Last 7",
    "last_15": "Last 15",
    "last_30": "Last 30",
}


def available_windows(league_id: int, version: str) -> list[str]:
    have = set(queries.player_z(league_id, version)["stat_window"])
    return [w for w in STAT_WINDOWS if w in have]


@st.cache_data(ttl=6 * 3600, max_entries=200, show_spinner=False)
def league(league_id: int, version: str, window: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(players, team totals) for one stat window."""
    z = queries.player_z(league_id, version)
    players = player_matrix(z.loc[z["stat_window"] == window])
    return players, team_totals(players)


@st.cache_data(ttl=6 * 3600, max_entries=200, show_spinner=False)
def weights_by_team(
    league_id: int, version: str, window: str, me: int, delta: float, overrides: tuple
) -> dict:
    """Every team's weights; only `me` gets the user's overrides."""
    _, totals = league(league_id, version, window)
    return {
        t: compute_weights(totals, t, delta, dict(overrides) if t == me else None)
        for t in totals.index
    }


@st.cache_data(ttl=6 * 3600, max_entries=50, show_spinner="Searching every trade...")
def all_trades(
    league_id: int, version: str, window: str, me: int, delta: float, overrides: tuple
) -> pd.DataFrame:
    players, totals = league(league_id, version, window)
    weights = weights_by_team(league_id, version, window, me, delta, overrides)
    return find_trades(players, totals, me, weights, top=5000)


@st.cache_data(ttl=6 * 3600, max_entries=100, show_spinner="Building trades for this player...")
def target_trades(
    league_id: int, version: str, window: str, me: int, target: int, delta: float, overrides: tuple
) -> pd.DataFrame:
    players, totals = league(league_id, version, window)
    weights = weights_by_team(league_id, version, window, me, delta, overrides)
    return deals_for_target(players, totals, me, target, weights)


@st.cache_data(ttl=6 * 3600, max_entries=200, show_spinner=False)
def empty_slot(league_id: int, version: str, window: str) -> pd.Series:
    """What an empty roster spot is worth per category (z) in this window. Blended
    mixes season and projected per player, so its empty spot is the average of the
    two windows' (whichever exist)."""
    z = queries.player_z(league_id, version)
    raw = ["season", "projected"] if window == "blended" else [window]
    found = [
        empty_slot_z(z.loc[z["stat_window"] == w]) for w in raw if (z["stat_window"] == w).any()
    ]
    return pd.concat(found, axis=1).mean(axis=1) if found else pd.Series(dtype=float)
