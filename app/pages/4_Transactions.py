"""Transactions page (Step 6): team/action filters; activity log table and an
adds/drops-per-team bar chart. Reads v_transactions.
"""

import plotly.graph_objects as go
import streamlit as st

import queries
import ui

st.title("Transactions")

txns = queries.transactions()
if txns.empty:
    st.info("No transactions yet this season.")
    st.stop()

ACTION_TYPES = ["ADD", "DROP", "TRADE", "OTHER"]
c1, c2 = st.columns(2)
teams = c1.multiselect("Teams", sorted(txns["team_name"].dropna().unique()), placeholder="All")
types = c2.multiselect(
    "Actions",
    [t for t in ACTION_TYPES if t in set(txns["action_type"])],
    format_func=str.title,
    placeholder="All",
)

shown = txns
if teams:
    shown = shown.loc[shown["team_name"].isin(teams)]
if types:
    shown = shown.loc[shown["action_type"].isin(types)]

st.subheader("Activity per team")
c = ui.colors()
# Colors follow the action, never its position, so filtering never repaints a bar.
action_colors = {"ADD": c["series"][0], "DROP": c["series"][1], "TRADE": c["series"][2]}
counts = shown.groupby(["team_name", "action_type"]).size().unstack(fill_value=0)
counts = counts.loc[counts.sum(axis=1).sort_values().index]
fig = go.Figure()
for action in ACTION_TYPES:
    if action in counts:
        fig.add_trace(
            go.Bar(
                x=counts[action],
                y=counts.index,
                orientation="h",
                name=action.title(),
                marker={"color": action_colors.get(action, c["muted"])},
                hovertemplate="%{y}: %{x} " + action.lower() + "<extra></extra>",
            )
        )
fig.update_layout(barmode="stack", bargap=0.25)
fig.update_xaxes(dtick=1 if counts.to_numpy().sum() < 10 else None, title="Transactions")
ui.show(ui.style(fig, height=max(240, 30 * len(counts) + 100)))

st.subheader("Activity log")
log = shown.sort_values("txn_date", ascending=False).assign(
    when=lambda d: d["txn_date"].dt.tz_convert(ui.LEAGUE_TZ).dt.strftime("%b %-d, %-I:%M %p")
)
st.dataframe(
    log[["when", "team_name", "action", "player_name"]],
    column_config={
        "when": "When (AZ)",
        "team_name": "Team",
        "action": "Action",
        "player_name": "Player",
    },
    hide_index=True,
    width="stretch",
)
