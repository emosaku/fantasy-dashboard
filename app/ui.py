"""Shared look: chart colors for the active light/dark theme, Plotly defaults, the
sidebar freshness note and Refresh button, and the footer.

Colors are the validated default data-viz palette. Categorical slots are used in
fixed order and capped at 3 per chart (the first three are the ones that stay
colorblind-distinguishable all-pairs). Diverging scales are red <-> blue with a gray
midpoint. Each mode has its own steps, picked from Streamlit's active theme.
"""

from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import league
import refresh
import tenancy

LIGHT = {
    "series": ["#2a78d6", "#eb6834", "#1baf7a"],
    "negative": "#e34948",
    "positive": "#2a78d6",
    "midpoint": "#f0efec",
    "muted": "#c3c2b7",
    "grid": "#e1e0d9",
    "up": "#006300",
    "down": "#d03b3b",
}
DARK = {
    "series": ["#3987e5", "#d95926", "#199e70"],
    "negative": "#e66767",
    "positive": "#3987e5",
    "midpoint": "#383835",
    "muted": "#52514e",
    "grid": "#2c2c2a",
    "up": "#0ca30c",
    "down": "#e66767",
}


def viewer_tz() -> ZoneInfo:
    """The viewer's own time zone, from their browser (UTC if it doesn't say)."""
    try:
        return ZoneInfo(st.context.timezone or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def local_time(ts) -> str:
    return f"{pd.Timestamp(ts).tz_convert(viewer_tz()):%b %-d, %-I:%M %p}"


PLOTLY_CONFIG = {"displayModeBar": False}  # the toolbar crowds a phone screen


def colors() -> dict:
    try:
        dark = st.context.theme.type == "dark"
    except AttributeError:
        dark = False
    return DARK if dark else LIGHT


def diverging_scale() -> list[list]:
    c = colors()
    return [[0.0, c["negative"]], [0.5, c["midpoint"]], [1.0, c["positive"]]]


def style(fig: go.Figure, height: int = 400) -> go.Figure:
    fig.update_layout(
        height=height,
        margin={"l": 8, "r": 8, "t": 32, "b": 8},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
        hoverlabel={"namelength": -1},
    )
    return fig


def _mix(a: str, b: str, t: float) -> str:
    """Blend two #rrggbb colors: t=0 -> a, t=1 -> b."""
    ca = [int(a[i : i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb, strict=True))


def rank_cell_style(rank: float, worst: int) -> str:
    """CSS for a table cell shaded by rank, the same scale as the team rankings grid:
    rank 1 blue, the middle gray, the last red."""
    c = colors()
    if rank != rank or worst <= 1:  # NaN or a single row
        return ""
    t = (rank - 1) / (worst - 1)
    background = (
        _mix(c["positive"], c["midpoint"], t * 2)
        if t <= 0.5
        else _mix(c["midpoint"], c["negative"], (t - 0.5) * 2)
    )
    text = "#ffffff" if c is DARK else "#0b0b0b"
    return f"background-color: {background}; color: {text}"


def table_height(rows: int) -> int:
    """Pixel height that shows every row of an st.dataframe without inner scrolling."""
    return 35 * (rows + 1) + 3


def show(fig: go.Figure) -> None:
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)


def sidebar_league(ctx) -> None:
    """Freshness note and the Refresh button for the open league. Data refreshes on
    its own every morning; the button pulls from ESPN on demand, once an hour."""
    loaded = ctx.doc.get("last_ingested_at")
    if loaded:
        st.sidebar.caption(f"Data updated {local_time(loaded)}")
    ready_at = tenancy.refresh_available_at(ctx.doc)
    now = league.now()
    ready = ready_at is None or now >= ready_at
    clicked = st.sidebar.button(
        "Refresh data",
        icon=":material/refresh:",
        disabled=not ready,
        help="Pull the latest from ESPN now (a few minutes). Also runs on its own every morning."
        if ready
        else f"Available again {local_time(ready_at)} (once an hour per league).",
    )
    if not clicked:
        return
    with st.sidebar.status("Pulling the latest from ESPN...") as status:
        try:
            tenancy.claim_refresh(league.db(), ctx.doc, now)
            before = ctx.doc.get("last_ingested_at")
            refresh.ingest_league(ctx.league_id)

            def landed() -> bool:
                latest = tenancy.get_league(league.db(), ctx.league_id).get("last_ingested_at")
                return latest is not None and (before is None or latest > before)

            if not refresh.wait_for(landed):
                status.update(label="Still running", state="running")
                st.sidebar.info("The refresh is taking a while; reload in a few minutes.")
                return
        except Exception as error:  # surface any failure in the sidebar, not a traceback
            status.update(label="Refresh failed", state="error")
            st.sidebar.error(str(error))
            return
        status.update(label="Updated", state="complete")
    league.forget_league_cache()  # the new last_ingested_at becomes every query's key
    st.rerun()


def footer() -> None:
    st.divider()
    st.caption(
        "League Lab is an independent, non-commercial project. It is not affiliated "
        "with, endorsed by or sponsored by ESPN or the NBA. It only reads league data, "
        "never changes it. [Privacy](/privacy)"
    )
