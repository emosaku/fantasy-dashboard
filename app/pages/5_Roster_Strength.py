"""Roster Strength page (Step 6): stat-window selector (7/15/30 days); team x category
heatmap of z-scores. Reads v_roster_strength.
"""

import plotly.graph_objects as go
import streamlit as st

import queries
import ui
from categories import COLUMNS, LABELS, fmt

st.title("Roster Strength")
st.caption(
    "Each roster's combined per-game stats (IR excluded), compared with the league. "
    "Blue is above average, red below; the number is the roster's actual value."
)

strength = queries.roster_strength()
if strength.empty:
    st.info("No roster data yet.")
    st.stop()

WINDOWS = {
    "last_7": "Last 7 days",
    "last_15": "Last 15 days",
    "last_30": "Last 30 days",
    "season": "Season",
    "projected": "Projected",
}
available = [w for w in WINDOWS if w in set(strength["stat_window"])]
window = st.segmented_control(
    "Stats from",
    available,
    default="last_15" if "last_15" in available else available[0],
    format_func=WINDOWS.get,
    required=True,
)
if "last_15" not in available:
    st.caption("Recent-form windows appear once games have been played.")

rows = strength.loc[strength["stat_window"] == window].copy()
rows["overall"] = rows[[f"{col}_z" for col in COLUMNS]].mean(axis=1)
rows = rows.sort_values("overall")  # Plotly draws the first row at the bottom

z = rows[[f"{col}_z" for col in COLUMNS]].to_numpy()
text = [[fmt(col, v) for col, v in zip(COLUMNS, r, strict=True)] for r in rows[COLUMNS].to_numpy()]
fig = go.Figure(
    go.Heatmap(
        z=z,
        x=[LABELS[col] for col in COLUMNS],
        y=rows["team_name"],
        text=text,
        texttemplate="%{text}",
        textfont={"size": 11},
        colorscale=ui.diverging_scale(),
        zmid=0,
        zmin=-2.5,
        zmax=2.5,
        xgap=2,
        ygap=2,
        colorbar={"title": "SD", "thickness": 10, "tickformat": "+.0f"},
        hovertemplate="<b>%{y}</b><br>%{x}: %{text} (%{z:+.2f} SD)<extra></extra>",
    )
)
fig.update_xaxes(side="top")
ui.show(ui.style(fig, height=36 * len(rows) + 80))

with st.expander("Table view"):
    table = rows.sort_values("overall", ascending=False)
    st.dataframe(
        table[["team_name", "players", *COLUMNS]],
        column_config={
            "team_name": "Team",
            "players": st.column_config.NumberColumn("Players", width="small"),
            **{
                col: st.column_config.NumberColumn(
                    LABELS[col], format="%.3f" if col.endswith("_pct") else "%.1f"
                )
                for col in COLUMNS
            },
        },
        hide_index=True,
        width="stretch",
    )
