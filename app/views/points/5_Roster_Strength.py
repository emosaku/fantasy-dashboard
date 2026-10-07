"""Roster Strength for a points league: teams ranked by projected weekly points,
from each day's best legal lineup over the rest of the regular season (the daily
lineup simulation), with this week's projection and games, bench depth, and where
each team's points come from. Reads the engine (points/data.py)."""

import pandas as pd
import streamlit as st

import queries
import ui
from points import data, model, view

ctx = view.header("Roster Strength")
window = view.window_picker(ctx, key="strength-window")
setup = data.for_context(ctx, window)
players = setup.players
lines = data.stat_lines(ctx.league_id, ctx.version, window)
by_stat = model.points_by_stat(lines.reindex(players.index), list(ctx.scoring))
sources = model.points_by_source(by_stat, list(ctx.scoring), players["fpg"])
schedule = queries.pro_schedule(ctx.league_id, ctx.version)
week_games = model.week_games(schedule, [ctx.current_week])[ctx.current_week]
weeks = len(setup.weeks)

rows, by_source, detail = [], {}, {}
for team in setup.teams:
    roster = setup.roster(team)
    sim = setup.full_weeks(roster)
    starts = pd.Series(sim["starts"], dtype="float64").reindex(roster).fillna(0) / weeks
    healthy_now = players.loc[roster, "back"] <= ctx.current_week
    games_now = players.loc[roster, "pro_team"].map(week_games).fillna(0) * healthy_now
    bench = players.loc[roster, "fpg"].sort_values(ascending=False).iloc[setup.starting :]
    rows.append(
        {
            "team_id": team,
            "Team": view.team_label(ctx, team),
            "Projected points a week": setup.full_mu(roster),
            "This week": sim["weeks"].get(ctx.current_week, 0.0),
            "Games this week": int(games_now.sum()),
            "Bench FP/G": float(bench.mean()) if len(bench) else float("nan"),
        }
    )
    by_source[team] = sources.loc[roster].mul(starts, axis=0).sum()
    detail[team] = pd.DataFrame(
        {
            "Player": players.loc[roster, "player_name"],
            "Slots": players.loc[roster, "eligible_slots"].map(lambda s: view.slots_text(ctx, s)),
            "Status": [view.status_text(r) for _, r in players.loc[roster].iterrows()],
            "FP/G": players.loc[roster, "fpg"],
            "Games a week": players.loc[roster, "games"],
            "Starts a week": starts,
            "Points a week": starts * players.loc[roster, "fpg"],
        }
    ).sort_values("Points a week", ascending=False)

table = pd.DataFrame(rows).sort_values("Projected points a week", ascending=False)
table.insert(0, "#", range(1, len(table) + 1))
e = model.expected_wins(table.set_index("team_id")["Projected points a week"], setup.sigma)
table["Expected wins a week"] = table["team_id"].map(e)

st.caption(
    f"Rest of the regular season (weeks {setup.weeks[0]}-{setup.weeks[-1]}): each day, the "
    "best legal lineup from the players with a game, using the league's lineup slots and "
    "each player's eligible slots. Injured players count from the week they're expected "
    "back. IR players are left out."
)
st.dataframe(
    table.drop(columns="team_id"),
    column_config={
        "#": st.column_config.NumberColumn(width="small"),
        "Projected points a week": st.column_config.NumberColumn(format="%.1f"),
        "This week": st.column_config.NumberColumn(
            f"Week {ctx.current_week} projection", format="%.1f",
            help="This whole week from today's rosters (games already played included).",
        ),
        "Bench FP/G": st.column_config.NumberColumn(
            format="%.1f", help=f"Average FP/G outside the {setup.starting} best players."
        ),
        "Expected wins a week": st.column_config.NumberColumn(
            format="%.2f", help=f"All-play, out of {len(table) - 1}."
        ),
    },
    hide_index=True,
    width="stretch",
    height=ui.table_height(len(table)),
)  # fmt: skip

st.subheader("Points a week by source")
st.caption(
    "Where each team's projected weekly points come from: each starter's per-game points "
    "from each stat, times how often he starts. Shaded by rank in each column. Other is "
    "anything ESPN scores that the stat line doesn't show (bonuses like double-doubles)."
)
src = pd.DataFrame(by_source).T.reindex(table["team_id"])
src = src.loc[:, (src.abs() > 1e-9).any()]
src.index = [view.team_label(ctx, t) for t in src.index]
worst = len(src)
styled = src.style.format("{:.1f}").apply(
    lambda col: [ui.rank_cell_style(r, worst) for r in col.rank(ascending=False)], axis=0
)
st.dataframe(styled, width="stretch", height=ui.table_height(len(src)))

st.subheader("Lineups")
team = st.selectbox(
    "Team",
    list(table["team_id"]),
    index=list(table["team_id"]).index(ctx.my_team) if ctx.my_team in set(table["team_id"]) else 0,
    format_func=lambda t: view.team_label(ctx, t),
    key="strength-team",
)
st.dataframe(
    detail[team],
    column_config={
        "FP/G": st.column_config.NumberColumn(format="%.1f"),
        "Games a week": st.column_config.NumberColumn(format="%.1f"),
        "Starts a week": st.column_config.NumberColumn(
            format="%.1f", help="Games he's in the best lineup, a week on average."
        ),
        "Points a week": st.column_config.NumberColumn(format="%.1f"),
    },
    hide_index=True,
    width="stretch",
    height=ui.table_height(len(detail[team])),
)
