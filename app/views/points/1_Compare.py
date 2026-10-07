"""Compare for a points league. Teams: two teams' weekly points side by side, their
projections and where their points come from. Players: up to four players' fantasy
points per game in every window, points above replacement, games, health, and their
points per game by source. Reads matchup_scores, player_points, m_player_pool."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import queries
import ui
from points import data, model, view

ctx = view.header("Compare")
c1, c2 = st.columns([1, 1])
mode = c1.radio("Compare", ["Teams", "Players"], horizontal=True, key="compare-mode")
window = view.window_picker(ctx, c2, key="compare-window")
setup = data.for_context(ctx, window)
players = setup.players
colors = ui.colors()
lines = data.stat_lines(ctx.league_id, ctx.version, window)
by_stat = model.points_by_stat(lines.reindex(players.index), list(ctx.scoring))
sources = model.points_by_source(by_stat, list(ctx.scoring), players["fpg"])

if mode == "Teams":
    team_ids = list(setup.teams)
    first = ctx.my_team if ctx.my_team in team_ids else team_ids[0]
    t1, t2 = st.columns(2)
    a = t1.selectbox("Team", team_ids, index=team_ids.index(first),
                     format_func=lambda t: view.team_label(ctx, t), key="compare-a")  # fmt: skip
    others = [t for t in team_ids if t != a]
    b = t2.selectbox("Against", others, format_func=lambda t: view.team_label(ctx, t),
                     key="compare-b")  # fmt: skip
    mu = setup.team_mu(full=True)
    e = model.expected_wins(mu, setup.sigma)
    table = model.season_table(data.results(ctx.league_id, ctx.version, ctx.current_week))
    m1, m2 = st.columns(2)
    for col, team in ((m1, a), (m2, b)):
        col.markdown(f"**{view.team_label(ctx, team)}**")
        x, y = col.columns(2)
        x.metric("Projected points a week", f"{mu[team]:,.1f}")
        y.metric("Expected wins a week", f"{e[team]:.2f}", help=f"Out of {len(mu) - 1}.")
        if team in table.index:
            r = table.loc[team]
            col.caption(
                f"Record {int(r['wins'])}-{int(r['losses'])}-{int(r['ties'])} · "
                f"{r['points_per_week']:,.1f} points a week so far · all-play "
                f"{int(r['ap_wins'])}-{int(r['ap_losses'])}-{int(r['ap_ties'])}"
            )
    beats = float(model.phi([(mu[a] - mu[b]) / (setup.sigma * 2**0.5)])[0])
    st.caption(
        f"In a week against each other, {view.team_label(ctx, a)} would outscore "
        f"{view.team_label(ctx, b)} {beats:.0%} of the time."
    )

    results = data.results(ctx.league_id, ctx.version, ctx.current_week)
    if not results.empty:
        st.subheader("Weekly points")
        fig = go.Figure()
        for i, (team, dash) in enumerate(((a, "solid"), (b, "dash"))):
            rows = results.loc[results["team_id"] == team].sort_values("matchup_period")
            fig.add_trace(
                go.Scatter(
                    x=rows["matchup_period"], y=rows["points"], name=view.team_label(ctx, team),
                    mode="lines+markers", line={"color": colors["series"][i], "width": 2,
                                                "dash": dash},
                    marker={"size": 8},
                    hovertemplate="Week %{x}: %{y:,.1f}<extra>%{fullData.name}</extra>",
                )
            )  # fmt: skip
        fig.update_xaxes(title="Week", dtick=1)
        fig.update_yaxes(title="Points")
        ui.show(ui.style(fig, height=340))

    st.subheader("Points a week by source")
    st.caption("Each starter's per-game points by stat, times how often he starts.")
    weeks = len(setup.weeks)
    split = {}
    for team in (a, b):
        roster = setup.roster(team)
        starts = pd.Series(setup.full_weeks(roster)["starts"], dtype="float64").reindex(roster)
        split[view.team_label(ctx, team)] = sources.loc[roster].mul(starts / weeks, axis=0).sum()
    split = pd.DataFrame(split)
    split = split.loc[(split.abs() > 1e-9).any(axis=1)]
    split["Difference"] = split.iloc[:, 0] - split.iloc[:, 1]
    st.dataframe(split.style.format("{:+.1f}", subset=["Difference"]).format(
        "{:.1f}", subset=split.columns[:2]), width="stretch")  # fmt: skip
    st.stop()

# --- Players ------------------------------------------------------------------------------
pool = players.loc[players["fpg"].notna()].sort_values("fpg", ascending=False)
options = [int(p) for p in pool.index]
# "compare-players" is also set by the Trade Analyzer's Compare players buttons.
picked = st.session_state.get("compare-players")
if picked is None:
    picked = [int(p) for p in pool.index[pool["team_id"] == ctx.my_team]][:2]
st.session_state["compare-players"] = [p for p in picked if p in set(options)][:4]


def player_option(p) -> str:
    return f"{pool.at[p, 'player_name']} ({view.team_label(ctx, pool.at[p, 'team_id'])})"


chosen = st.multiselect(
    "Players", options, max_selections=4, format_func=player_option, key="compare-players"
)
if not chosen:
    st.info("Pick up to four players.")
    st.stop()
profile = queries.player_profile(ctx.league_id, ctx.version).set_index("player_id")
schedule = queries.pro_schedule(ctx.league_id, ctx.version)
this_week = model.week_games(schedule, [ctx.current_week])[ctx.current_week]
rows = {}
for pid in chosen:
    p = players.loc[pid]
    row = {
        "Team": view.team_label(ctx, p["team_id"]),
        "NBA": p["pro_team"],
        "Slots": view.slots_text(ctx, p["eligible_slots"]),
        "Status": view.status_text(p) or "Healthy",
        f"FP/G ({model.WINDOWS[window]})": p["fpg"],
        "PAR": p["par"],
    }
    for w, label in model.WINDOWS.items():
        if w != "blended" and f"fp_{w}" in players:
            row[f"FP/G {label}"] = p[f"fp_{w}"]
    row["Games this week"] = this_week.get(p["pro_team"], 0)
    row["Games left"] = p["games_left"]
    if pid in profile.index and pd.notna(profile.at[pid, "avg_games_played"]):
        row["Avg games, last 3 seasons"] = profile.at[pid, "avg_games_played"]
    rows[p["player_name"]] = row
st.dataframe(pd.DataFrame(rows).astype(str).replace({"nan": "–"}), width="stretch")

st.subheader("Points per game by source")
src = sources.loc[chosen]
src = src.loc[:, (src.abs() > 1e-9).any()]
fig = go.Figure()
patterns = ["", "/", ".", "x"]
for i, pid in enumerate(chosen):
    fig.add_trace(
        go.Bar(
            x=list(src.columns), y=src.loc[pid], name=players.at[pid, "player_name"],
            marker={"color": colors["series4"][i], "pattern": {"shape": patterns[i]},
                    "cornerradius": 4},
            hovertemplate="%{x}: %{y:.1f}<extra>%{fullData.name}</extra>",
        )
    )  # fmt: skip
fig.update_layout(barmode="group", bargap=0.2)
fig.update_yaxes(title="Points per game")
ui.show(ui.style(fig, height=360))
