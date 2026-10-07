"""Transactions page: every activity this season -- adds, drops, trades and
lineup moves. One filter bar (dates, team, action, player) drives both the
activity-per-team bar chart and the activity log, which lists every matching row.
Reads m_transactions.
"""

import plotly.graph_objects as go
import streamlit as st

import league
import queries
import ui

st.title("Transactions")
ctx = league.current()

txns = queries.transactions(ctx.league_id, ctx.version)
if txns.empty:
    st.info("No activity yet this season.")
    st.stop()

ACTION_LABELS = {
    "FA ADDED": "Free-agent add",
    "WAIVER ADDED": "Waiver add",
    "DROPPED": "Drop",
    "TRADED": "Trade",
    "MOVED": "Lineup move",
}
TYPE_LABELS = {
    "ADD": "Add",
    "DROP": "Drop",
    "TRADE": "Trade",
    "MOVE": "Lineup move",
    "OTHER": "Other",
}

txns = txns.assign(day=txns["txn_date"].dt.tz_convert(ui.viewer_tz()).dt.date)
first, last = txns["day"].min(), txns["day"].max()

f1, f2 = st.columns(2)
dates = f1.date_input("Dates", value=(first, last), min_value=first, max_value=last)
teams = f2.multiselect("Teams", sorted(txns["team_name"].dropna().unique()), placeholder="All")
f3, f4 = st.columns(2)
actions = f3.multiselect(
    "Actions",
    [a for a in ACTION_LABELS if a in set(txns["action"])]
    + sorted(set(txns["action"]) - set(ACTION_LABELS)),
    format_func=lambda a: ACTION_LABELS.get(a, a.title()),
    placeholder="All",
)
players = f4.multiselect(
    "Players", sorted(txns["player_name"].dropna().unique()), placeholder="All"
)

shown = txns
if isinstance(dates, tuple) and len(dates) == 2:  # mid-selection it's a single date
    shown = shown.loc[shown["day"].between(dates[0], dates[1])]
if teams:
    shown = shown.loc[shown["team_name"].isin(teams)]
if actions:
    shown = shown.loc[shown["action"].isin(actions)]
if players:
    shown = shown.loc[shown["player_name"].isin(players)]
st.caption(f"Showing {len(shown):,} of {len(txns):,} activities this season.")

if shown.empty:
    st.info("Nothing matches these filters.")
    st.stop()

st.subheader("Activity per team")
c = ui.colors()
# Colors follow the action, never its position, so filtering never repaints a bar.
# Lineup moves are routine roster upkeep, so they stay a quiet gray.
type_colors = {
    "ADD": c["series"][0],
    "DROP": c["series"][1],
    "TRADE": c["series"][2],
    "MOVE": c["muted"],
}
counts = shown.groupby(["team_name", "action_type"]).size().unstack(fill_value=0)
counts = counts.loc[counts.sum(axis=1).sort_values().index]
fig = go.Figure()
for action_type in TYPE_LABELS:
    if action_type in counts:
        fig.add_trace(
            go.Bar(
                x=counts[action_type],
                y=counts.index,
                orientation="h",
                name=TYPE_LABELS[action_type],
                marker={"color": type_colors.get(action_type, c["muted"])},
                text=counts[action_type].where(counts[action_type] > 0, ""),
                textposition="inside",
                insidetextanchor="middle",
                textangle=0,
                hovertemplate="%{y}: %{x} " + TYPE_LABELS[action_type].lower() + "<extra></extra>",
            )
        )
# Each team's total, just past the end of its bar.
totals = counts.sum(axis=1)
fig.add_trace(
    go.Scatter(
        x=totals,
        y=totals.index,
        mode="text",
        text=" " + totals.astype(str),  # a space so it doesn't touch the bar
        textposition="middle right",
        showlegend=False,
        hoverinfo="skip",
    )
)
fig.update_layout(
    barmode="stack",
    bargap=0.25,
    uniformtext={"mode": "hide", "minsize": 10},
    legend={"traceorder": "normal"},
)
fig.update_xaxes(
    range=[0, totals.max() * 1.12 + 0.5],
    dtick=1 if totals.max() < 10 else None,
    title="Activities",
)
ui.show(ui.style(fig, height=max(240, 30 * len(counts) + 100)))

st.subheader("Activity log")
log = shown.sort_values("txn_date", ascending=False).assign(
    when=lambda d: d["txn_date"].dt.tz_convert(ui.viewer_tz()).dt.strftime("%b %-d, %-I:%M %p"),
    action_label=lambda d: d["action"].map(lambda a: ACTION_LABELS.get(a, a.title())),
    detail=lambda d: d["detail"].fillna(""),  # only lineup moves have details
)
st.dataframe(
    log[["when", "team_name", "action_label", "player_name", "detail"]],
    column_config={
        "when": "When",
        "team_name": "Team",
        "action_label": "Action",
        "player_name": "Player",
        "detail": st.column_config.TextColumn("Details", help="Lineup moves: from slot to slot"),
    },
    hide_index=True,
    width="stretch",
    height=ui.table_height(len(log)),  # every matching row, no scrolling inside the table
)
