"""Matchups and Luck for a points league: each week's score cards with the margin,
the highest scores in a loss, and luck (actual win % minus all-play win %, season to
date). Reads matchup_scores."""

import plotly.graph_objects as go
import streamlit as st

import queries
import ui
from points import data, model, view

ctx = view.header("Matchups and Luck")
scores = queries.matchup_scores(ctx.league_id, ctx.version)
if scores.empty:
    st.info("No matchup data yet.")
    st.stop()
names = ctx.team_names
weeks = sorted(w for w in scores["matchup_period"].unique() if w <= ctx.current_week)
week = st.selectbox("Week", weeks[::-1], format_func=lambda w: f"Week {w}")
this_week = scores.loc[(scores["matchup_period"] == week) & scores["is_home"]]

st.subheader(f"Week {week} scores")
if week == ctx.current_week:
    st.caption("This week is still being played: live scores.")
grid = st.columns(2)
for i, row in enumerate(this_week.itertuples()):
    home, away = names.get(row.team_id, "?"), names.get(row.opponent_id, "?")
    with grid[i % 2].container(border=True):
        if row.points == 0 and row.opponent_points == 0:
            st.markdown(f"**{home}** vs **{away}**  \nNot played yet")
            continue
        margin = abs(row.points - row.opponent_points)
        lead = home if row.points > row.opponent_points else away
        verb = "leads" if week == ctx.current_week else "wins"
        st.markdown(
            f"{home} **{row.points:,.1f}**  \n{away} **{row.opponent_points:,.1f}**  \n"
            + ("Tied" if margin == 0 else f"{lead} {verb} by {margin:,.1f}")
        )

results = data.results(ctx.league_id, ctx.version, ctx.current_week)
if results.empty:
    st.info("Luck shows once a week has been played.")
    st.stop()

losses = results.loc[results["result"] == "L"].nlargest(3, "points")
if not losses.empty:
    st.subheader("Highest scores in a loss")
    for row in losses.itertuples():
        st.markdown(
            f"- **{names.get(row.team_id, '?')}**, week {row.matchup_period}: {row.points:,.1f} "
            f"(lost to {names.get(row.opponent_id, '?')}, {row.opponent_points:,.1f})"
        )

weekly = model.luck_by_week(results)
through = min(week, int(results["matchup_period"].max()))
board = weekly.loc[weekly["matchup_period"] == through].copy()
board["team"] = board["team_id"].map(lambda t: names.get(t, str(t)))
board = board.sort_values("luck")
st.subheader("Luck")
st.caption(
    f"Season to date through week {through}: actual win % minus all-play win % (how often "
    "the team outscored each other team). Positive means a better record than its points "
    "have earned."
)
c = ui.colors()
fig = go.Figure(
    go.Bar(
        x=board["luck"],
        y=board["team"],
        orientation="h",
        marker={
            "color": [c["positive"] if v > 0 else c["negative"] for v in board["luck"]],
            "cornerradius": 4,
        },
        customdata=board[["actual_to_date", "ap_to_date"]],
        hovertemplate=(
            "<b>%{y}</b><br>Luck %{x:+.3f}<br>"
            "Actual win % %{customdata[0]:.3f}<br>All-play win % %{customdata[1]:.3f}"
            "<extra></extra>"
        ),
    )
)
span = max(0.1, float(board["luck"].abs().max()) * 1.1)
fig.update_xaxes(range=[-span, span], tickformat="+.2f", zeroline=True)
fig.update_layout(bargap=0.25)
ui.show(ui.style(fig, height=max(320, 30 * len(board) + 80)))
st.dataframe(
    board.sort_values("luck", ascending=False)[["team", "actual_to_date", "ap_to_date", "luck"]],
    column_config={
        "team": "Team",
        "actual_to_date": st.column_config.NumberColumn("Actual win %", format="%.3f"),
        "ap_to_date": st.column_config.NumberColumn("All-play win %", format="%.3f"),
        "luck": st.column_config.NumberColumn("Luck", format="%+.3f"),
    },
    hide_index=True,
    width="stretch",
    height=ui.table_height(len(board)),
)
