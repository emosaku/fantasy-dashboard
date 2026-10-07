"""Power Rankings for a points league: all-play by weekly points (each week a team
beats every team it outscored), and each team's projected finish from its projected
weekly points (the daily lineup simulation) and the league's week-to-week spread.
Reads matchup_scores, the engine for projections."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import queries
import ui
from points import data, model, view

ctx = view.header("Power Rankings")
window = view.window_picker(ctx, key="power-window")
results = data.results(ctx.league_id, ctx.version, ctx.current_week)
table = model.season_table(results)
names = ctx.team_names

st.subheader("All-play")
if table.empty:
    st.info("No weeks played yet. Projections are below.")
else:
    table = table.assign(team=[names.get(t, str(t)) for t in table.index])
    table["power_rank"] = table["ap_win_pct"].rank(ascending=False, method="min").astype(int)
    table = table.sort_values(["power_rank", "points_for"], ascending=[True, False])
    table["All-play"] = (
        table["ap_wins"].astype(str) + "-" + table["ap_losses"].astype(str) + "-"
        + table["ap_ties"].astype(str)
    )  # fmt: skip
    table["Record"] = (
        table["wins"].astype(str) + "-" + table["losses"].astype(str) + "-"
        + table["ties"].astype(str)
    )  # fmt: skip
    st.caption(
        "Each week, a team beats every team it outscored. Ranked by all-play win % "
        f"through week {int(results['matchup_period'].max())}; level teams share a rank."
    )
    st.dataframe(
        table[["power_rank", "team", "All-play", "ap_win_pct", "Record", "points_per_week",
               "luck"]],
        column_config={
            "power_rank": st.column_config.NumberColumn("#", width="small"),
            "team": "Team",
            "ap_win_pct": st.column_config.NumberColumn("All-play win %", format="%.3f"),
            "points_per_week": st.column_config.NumberColumn("Points a week", format="%.1f"),
            "luck": st.column_config.NumberColumn(
                "Luck", format="%+.3f", help="Actual win % minus all-play win %."
            ),
        },
        hide_index=True,
        width="stretch",
        height=ui.table_height(len(table)),
    )  # fmt: skip

st.subheader("Projected finish")
setup = data.for_context(ctx, window)
mu = setup.team_mu(full=True)
e = model.expected_wins(mu, setup.sigma)
schedule = queries.pro_schedule(ctx.league_id, ctx.version)
left = data.share_of_week_left(schedule, ctx.current_week, data.today())
finish = model.projected_finish(
    queries.matchup_scores(ctx.league_id, ctx.version), mu, setup.sigma, ctx.current_week,
    ctx.last_week, left,
)  # fmt: skip
proj = pd.DataFrame(
    {
        "team": [names.get(t, str(t)) for t in finish.index],
        "mu": mu.reindex(finish.index),
        "e": e.reindex(finish.index),
        "wins": finish["wins"],
        "losses": finish["losses"],
    },
    index=finish.index,
).sort_values(["wins", "mu"], ascending=False)
proj["Projected record"] = [
    f"{w:.1f}-{lo:.1f}" + (f"-{int(t)}" if t else "")
    for w, lo, t in zip(proj["wins"], proj["losses"], finish["ties"].reindex(proj.index),
                        strict=True)
]  # fmt: skip
st.caption(
    f"Weeks played count as they happened; every remaining regular-season matchup (through "
    f"week {ctx.last_week}) is won with the chance one team outscores the other, from "
    f"projected weekly points (today's rosters, injuries, the NBA schedule) and a "
    f"week-to-week spread of {setup.sigma:,.0f} points ({setup.spread_note})."
)
st.dataframe(
    proj[["team", "Projected record", "mu", "e"]],
    column_config={
        "team": "Team",
        "mu": st.column_config.NumberColumn(
            "Projected points a week", format="%.1f",
            help="The rest of the regular season, from each day's best legal lineup.",
        ),
        "e": st.column_config.NumberColumn(
            "Expected wins a week", format="%.2f",
            help=f"All-play: out of {len(mu) - 1}, the chance of outscoring each other team.",
        ),
    },
    hide_index=True,
    width="stretch",
    height=ui.table_height(len(proj)),
)  # fmt: skip

c = ui.colors()
order = proj.sort_values("mu")
fig = go.Figure(
    go.Bar(
        x=order["mu"],
        y=order["team"],
        orientation="h",
        marker={"color": c["series"][0], "cornerradius": 4},
        customdata=order[["e"]],
        hovertemplate="<b>%{y}</b><br>%{x:,.1f} points a week<br>"
        "%{customdata[0]:.2f} expected wins a week<extra></extra>",
    )
)
fig.update_xaxes(title="Projected points a week")
fig.update_layout(bargap=0.25)
ui.show(ui.style(fig, height=max(320, 30 * len(order) + 80)))
