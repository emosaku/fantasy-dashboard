"""Player Rankings for a points league: every rostered player and top free agent by
fantasy points per game in a stat window, with points above replacement, games this
week, and the points each stat earns him per game. Reads player_points and
m_player_pool."""

import pandas as pd
import streamlit as st

import queries
from points import data, model, view

ctx = view.header("Player Rankings")
c1, c2, c3 = st.columns([1, 1, 1.2])
window = view.window_picker(ctx, c1, key="rank-window")
who = c2.selectbox("Players", ["All", "Free agents", "Rostered", "My team"], key="rank-who")
slots = [s for s, _ in ctx.lineup_slots if s != "UT"]
slot = c3.multiselect("Can start at", slots, key="rank-slot", placeholder="Any slot")
search = st.text_input("Search", placeholder="Player name", key="rank-search")

players = data.players(ctx.league_id, ctx.version, window).copy()
replacement = model.replacement_level(players)
players["par"] = players["fpg"] - replacement
schedule = queries.pro_schedule(ctx.league_id, ctx.version)
this_week = model.week_games(schedule, [ctx.current_week])
players["games_week"] = players["pro_team"].map(this_week[ctx.current_week]).fillna(0)
by_stat = model.points_by_stat(data.stat_lines(ctx.league_id, ctx.version, window).reindex(
    players.index), list(ctx.scoring))  # fmt: skip

shown = players.loc[players["fpg"].notna()]
if who == "Free agents":
    shown = shown.loc[shown["is_free_agent"].astype(bool)]
elif who == "Rostered":
    shown = shown.loc[~shown["is_free_agent"].astype(bool)]
elif who == "My team":
    shown = shown.loc[shown["team_id"] == ctx.my_team]
if slot:
    shown = shown.loc[shown["eligible_slots"].map(lambda s: bool(model.slots_of(s) & set(slot)))]
if search:
    shown = shown.loc[shown["player_name"].str.contains(search, case=False, regex=False)]
shown = shown.sort_values("fpg", ascending=False)

st.caption(
    f"{len(shown)} players · replacement level {replacement:.1f} FP/G (the median of the 10 "
    "best healthy free agents) · stat columns are points per game from that stat."
)
table = pd.DataFrame(
    {
        "Rank": range(1, len(shown) + 1),
        "Player": shown["player_name"],
        "Team": [view.team_label(ctx, t) for t in shown["team_id"]],
        "NBA": shown["pro_team"],
        "Slots": shown["eligible_slots"].map(lambda s: view.slots_text(ctx, s)),
        "Status": [view.status_text(r) for _, r in shown.iterrows()],
        "FP/G": shown["fpg"],
        "PAR": shown["par"],
        "Games this week": shown["games_week"].astype(int),
        "Season FP": shown["total_season"] if "total_season" in shown else float("nan"),
    },
    index=shown.index,
).join(by_stat.loc[shown.index].add_suffix(" pts"))
number = {"format": "%.1f"}
st.dataframe(
    table,
    column_config={
        "FP/G": st.column_config.NumberColumn(help="Fantasy points per game.", **number),
        "PAR": st.column_config.NumberColumn(
            help="Points above replacement: FP/G minus replacement level.", format="%+.1f"
        ),
        "Season FP": st.column_config.NumberColumn(**number),
        **{f"{s['stat']} pts": st.column_config.NumberColumn(**number) for s in ctx.scoring},
    },
    hide_index=True,
    width="stretch",
    height=600,
)
