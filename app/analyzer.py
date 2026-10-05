"""Cached glue between the BigQuery views and app/analysis for the pages that use
the z-score foundation (Roster Strength's Category rankings, Trade Analyzer).

Everything is keyed on plain values (stat window, delta, overrides as a tuple), so
Streamlit caches each combination for an hour like the view reads it's built on.
"""

import pandas as pd
import streamlit as st

import queries
from analysis.pool import player_matrix, team_totals
from analysis.trades import find_trades
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


def team_names() -> pd.Series:
    return queries.teams().set_index("team_id")["team_name"].sort_values()
