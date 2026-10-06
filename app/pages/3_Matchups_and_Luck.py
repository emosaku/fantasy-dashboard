"""Matchups and Luck page: week picker; category scoreboard per matchup and a luck
bar chart (actual vs. all-play win %, at the level the league scores: matchups for
Most Categories, categories for Each Category). Reads m_luck, plus m_team_week_cats
for the scoreboard's category values.
"""

import plotly.graph_objects as go
import streamlit as st

import league
import queries
import ui
from categories import fmt

st.title("Matchups and Luck")
ctx = league.current()

luck = queries.luck(ctx.league_id, ctx.version)
week_cats = queries.team_week_cats(ctx.league_id, ctx.version)
if luck.empty:
    st.info("No matchup data yet.")
    st.stop()

weeks = sorted(luck["matchup_period"].unique(), reverse=True)
week = st.selectbox("Week", weeks, format_func=lambda w: f"Week {w}")
this_week = luck.loc[luck["matchup_period"] == week]
this_cats = week_cats.loc[week_cats["matchup_period"] == week]
values = this_cats.pivot(index="team_id", columns="category", values="value")
score = this_cats.pivot(index="team_id", columns="category", values="score")

st.subheader(f"Week {week} scoreboard")
st.caption(
    "Category scores are ESPN's. The winning value in each category is bold"
    + (
        " (fewer wins in lower-is-better categories)."
        if any(c.lower_is_better for c in ctx.cats)
        else "."
    )
)


def scoreboard(home: int, away: int) -> None:
    h = this_week.loc[this_week["team_id"] == home].iloc[0]
    if h.cat_wins + h.cat_losses + h.cat_ties == 0:  # ESPN hasn't scored it yet
        st.markdown("Not played yet")
    elif h.actual_result == "T":
        st.markdown(f"Tied {h.cat_wins}-{h.cat_losses}-{h.cat_ties}")
    else:
        winner = h.team_name if h.actual_result == "W" else h.opponent_name
        hi, lo = max(h.cat_wins, h.cat_losses), min(h.cat_wins, h.cat_losses)
        st.markdown(f"**{winner}** wins {hi}-{lo}-{h.cat_ties}")
    rows = []
    for cat in ctx.cats:
        hv, av = values.at[home, cat.key], values.at[away, cat.key]
        hscore, ascore = score.at[home, cat.key], score.at[away, cat.key]
        hs, as_ = fmt(cat, hv), fmt(cat, av)
        if hscore > ascore:
            hs = f"**{hs}**"
        elif ascore > hscore:
            as_ = f"**{as_}**"
        rows.append(f"| {hs} | {cat.label} | {as_} |")
    header = f"| {h.team_name} | | {h.opponent_name} |\n|--:|:-:|:--|\n"
    st.markdown(header + "\n".join(rows))


# One scoreboard per real matchup: each pair appears twice in v_luck, once per side.
pairs = this_week.loc[this_week["team_id"] < this_week["opponent_id"], ["team_id", "opponent_id"]]
grid = st.columns(2)
for i, (home, away) in enumerate(pairs.itertuples(index=False)):
    with grid[i % 2].container(border=True):
        scoreboard(home, away)

st.subheader("Luck")
st.caption(
    f"Season to date through week {week}: actual win % minus all-play win %"
    + (" (both counted in categories, as Each Category scores)" if ctx.each_category else "")
    + ". Positive means a better record than the team's stats have earned."
)
board = this_week.sort_values("luck")
c = ui.colors()
fig = go.Figure(
    go.Bar(
        x=board["luck"],
        y=board["team_name"],
        orientation="h",
        marker={
            "color": [c["positive"] if v > 0 else c["negative"] for v in board["luck"]],
            "cornerradius": 4,
        },
        customdata=board[["actual_win_pct_to_date", "ap_win_pct_to_date"]],
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
    board.sort_values("luck", ascending=False)[
        ["team_name", "actual_win_pct_to_date", "ap_win_pct_to_date", "luck"]
    ],
    column_config={
        "team_name": "Team",
        "actual_win_pct_to_date": st.column_config.NumberColumn("Actual win %", format="%.3f"),
        "ap_win_pct_to_date": st.column_config.NumberColumn("All-play win %", format="%.3f"),
        "luck": st.column_config.NumberColumn("Luck", format="%+.3f"),
    },
    hide_index=True,
    width="stretch",
    height=ui.table_height(len(board)),
)
