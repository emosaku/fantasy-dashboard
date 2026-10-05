"""Shared look: chart colors for the active light/dark theme, Plotly defaults, and
the sidebar freshness note.

Colors are the validated default data-viz palette. Categorical slots are used in
fixed order and capped at 3 per chart (the first three are the ones that stay
colorblind-distinguishable all-pairs). Diverging scales are red <-> blue with a gray
midpoint. Each mode has its own steps, picked from Streamlit's active theme.
"""

from zoneinfo import ZoneInfo

import plotly.graph_objects as go
import streamlit as st

import queries
import refresh

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
LEAGUE_TZ = ZoneInfo("America/Phoenix")
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


def table_height(rows: int) -> int:
    """Pixel height that shows every row of an st.dataframe without inner scrolling."""
    return 35 * (rows + 1) + 3


def show(fig: go.Figure) -> None:
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)


def sidebar_freshness() -> None:
    """'Data updated ...' plus a Refresh data button, on every page. Data refreshes on
    its own every morning; the button pulls from ESPN on demand (e.g. after a trade)."""
    ts = queries.last_updated()
    if ts is None:
        st.sidebar.caption("No data loaded yet.")
    else:
        local = ts.tz_convert(LEAGUE_TZ)
        st.sidebar.caption(f"Data updated {local:%b %-d, %-I:%M %p} Arizona time")

    ready = refresh.can_refresh(ts)
    clicked = st.sidebar.button(
        "Refresh data",
        icon=":material/refresh:",
        disabled=not ready,
        help="Pull the latest from ESPN now (about a minute). Also runs on its own "
        "every morning at 5 AM Arizona time."
        if ready
        else "Just updated. Available again 10 minutes after the last update.",
    )
    if clicked:
        with st.sidebar.status("Pulling the latest from ESPN...") as status:
            try:
                before = queries.latest_ingest_uncached()

                def landed() -> bool:
                    latest = queries.latest_ingest_uncached()
                    return latest is not None and (before is None or latest > before)

                refresh.run_ingest(landed)
            except Exception as error:  # surface any failure in the sidebar, not a traceback
                status.update(label="Refresh failed", state="error")
                st.sidebar.error(str(error))
                return
            status.update(label="Updated", state="complete")
        st.cache_data.clear()  # drop the hour-long query cache so pages re-read
        st.rerun()
