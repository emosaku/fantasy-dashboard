"""Power Rankings page (Step 6): week slider; ranked table with all-play record and
a rank-over-time line chart. Reads v_power_rankings.
"""

import plotly.graph_objects as go
import streamlit as st

import queries
import ui

st.title("Power Rankings")
st.caption(
    "Ranked by all-play: the record each team would have if it played every other "
    "team every week. Ties broken by categories won."
)

ranks = queries.power_rankings()
if ranks.empty:
    st.info("No matchup data yet.")
    st.stop()

weeks = sorted(ranks["matchup_period"].unique())
week = weeks[-1]
if len(weeks) > 1:
    week = st.select_slider(
        "Through week", options=weeks, value=weeks[-1], format_func=lambda w: f"Week {w}"
    )

now = ranks.loc[ranks["matchup_period"] == week].sort_values(["power_rank", "team_name"])
before = ranks.loc[ranks["matchup_period"] == week - 1].set_index("team_id")["power_rank"]
now = now.assign(
    move=now["team_id"].map(before) - now["power_rank"],
    record=now["ap_wins"].astype(str)
    + "-"
    + now["ap_losses"].astype(str)
    + "-"
    + now["ap_ties"].astype(str),
)


def movement(m: float) -> str:
    if m != m or m == 0:  # NaN (no prior week) or unchanged
        return "–"
    return f"▲ {int(m)}" if m > 0 else f"▼ {int(-m)}"


now["move"] = now["move"].map(movement)
st.dataframe(
    now[["power_rank", "team_name", "move", "record", "ap_win_pct", "ap_cat_win_pct"]],
    column_config={
        "power_rank": st.column_config.NumberColumn("#", width="small"),
        "team_name": "Team",
        "move": st.column_config.TextColumn("Move", help="Change since the previous week"),
        "record": st.column_config.TextColumn("All-play", help="Wins-losses-ties vs everyone"),
        "ap_win_pct": st.column_config.NumberColumn("Win %", format="%.3f"),
        "ap_cat_win_pct": st.column_config.NumberColumn(
            "Cat win %", format="%.3f", help="Share of categories won vs everyone"
        ),
    },
    hide_index=True,
    width="stretch",
    height=ui.table_height(len(now)),
)

st.subheader("Rank over time")
if len(weeks) < 2:
    st.info("This chart fills in once a second week has been played.")
    st.stop()

leaders = now["team_name"].head(3).tolist()
picked = st.multiselect(
    "Highlight teams (up to 3)",
    sorted(ranks["team_name"].unique()),
    default=leaders,
    max_selections=3,
)
c = ui.colors()
fig = go.Figure()
history = ranks.loc[ranks["matchup_period"] <= week].sort_values("matchup_period")
# Unpicked teams first, in gray, so the highlighted lines draw on top of them.
for name, team in history.groupby("team_name"):
    if name in picked:
        continue
    fig.add_trace(
        go.Scatter(
            x=team["matchup_period"],
            y=team["power_rank"],
            mode="lines",
            line={"color": c["muted"], "width": 1},
            name=name,
            showlegend=False,
            hovertemplate="Week %{x}: #%{y}<extra>" + name + "</extra>",
        )
    )
for name, color in zip(picked, c["series"], strict=False):
    team = history.loc[history["team_name"] == name]
    fig.add_trace(
        go.Scatter(
            x=team["matchup_period"],
            y=team["power_rank"],
            mode="lines+markers",
            line={"color": color, "width": 2},
            marker={"size": 8},
            name=name,
            hovertemplate="Week %{x}: #%{y}<extra>" + name + "</extra>",
        )
    )
fig.update_yaxes(autorange="reversed", dtick=1, title="Rank")
fig.update_xaxes(dtick=1, title="Week")
ui.show(ui.style(fig, height=440))
