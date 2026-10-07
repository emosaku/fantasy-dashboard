"""Home for a points league: standings with points for and against, and this
week's scores."""

import streamlit as st

import queries
import ui
from points import view


def render(ctx) -> None:
    st.title(ctx.name)
    st.caption(
        f"{view.season_label(ctx)} season · Head-to-head points · "
        + ", ".join(f"{s['stat']} {s['points']:+g}" for s in ctx.scoring)
    )
    teams = queries.teams(ctx.league_id, ctx.version).sort_values(["standing", "team_name"])
    teams["Record"] = (
        teams["wins"].astype(str) + "-" + teams["losses"].astype(str) + "-"
        + teams["ties"].astype(str)
    )  # fmt: skip
    teams["You"] = teams["team_id"].map(lambda t: "●" if t == ctx.my_team else "")
    st.subheader("Standings")
    st.dataframe(
        teams[["standing", "team_name", "You", "Record", "points_for", "points_against", "owner"]],
        column_config={
            "standing": st.column_config.NumberColumn("#", width="small"),
            "team_name": "Team",
            "You": st.column_config.TextColumn("", width="small"),
            "points_for": st.column_config.NumberColumn("Points for", format="%.1f"),
            "points_against": st.column_config.NumberColumn("Points against", format="%.1f"),
            "owner": "Manager",
        },
        hide_index=True,
        width="stretch",
        height=ui.table_height(len(teams)),
    )

    scores = queries.matchup_scores(ctx.league_id, ctx.version)
    week = scores.loc[scores["matchup_period"] == ctx.current_week]
    if week.empty:
        return
    st.subheader(f"Week {ctx.current_week}")
    names = ctx.team_names
    pairs = week.loc[week["is_home"]]
    grid = st.columns(2)
    for i, row in enumerate(pairs.itertuples()):
        with grid[i % 2].container(border=True):
            home, away = names.get(row.team_id, "?"), names.get(row.opponent_id, "?")
            if row.points == 0 and row.opponent_points == 0:
                st.markdown(f"**{home}** vs **{away}**  \nNot started")
            else:
                st.markdown(
                    f"**{home}** {row.points:,.1f}  \n**{away}** {row.opponent_points:,.1f}"
                )
    if week["is_playoff"].any():
        st.caption("Playoffs.")
