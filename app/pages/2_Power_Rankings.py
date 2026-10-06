"""Power Rankings page: week slider; ranked table with all-play record, a projected
finish through the end of the regular season that leaves injured players out of the
weeks they're expected to miss (app/analysis/projection.py), and a rank-over-time
line chart. Ranks follow the league's scoring: matchup win % for Most Categories,
category win % for Each Category. Reads m_power_rankings, m_all_play and
m_player_pool; season length from the registry.
"""

import plotly.graph_objects as go
import streamlit as st

import league
import queries
import ui
from analysis.projection import InjuryRules, availability, per_game_lines, project_season

st.title("Power Rankings")
ctx = league.current()
measure = "category win %" if ctx.each_category else "win %"
st.caption(
    "Ranked by all-play: the record each team would have if it played every other "
    f"team every week. This league scores {ctx.scoring_label}, so teams are ranked on "
    f"{measure}; teams level on it share a rank."
)

ranks = queries.power_rankings(ctx.league_id, ctx.version)
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
prefix = "ap_cat_" if ctx.each_category else "ap_"  # categories or matchups
now = now.assign(
    move=now["team_id"].map(before) - now["power_rank"],
    record=now[f"{prefix}wins"].astype(str)
    + "-"
    + now[f"{prefix}losses"].astype(str)
    + "-"
    + now[f"{prefix}ties"].astype(str),
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
        "record": st.column_config.TextColumn(
            "All-play",
            help="Category wins-losses-ties vs everyone"
            if ctx.each_category
            else "Wins-losses-ties vs everyone",
        ),
        "ap_win_pct": st.column_config.NumberColumn("Win %", format="%.3f"),
        "ap_cat_win_pct": st.column_config.NumberColumn(
            "Cat win %", format="%.3f", help="Share of categories won vs everyone"
        ),
    },
    hide_index=True,
    width="stretch",
    height=ui.table_height(len(now)),
)


def record(wins, losses, ties) -> list[str]:
    return [f"{w:g}-{lo:g}-{t:g}" for w, lo, t in zip(wins, losses, ties, strict=True)]


st.subheader("Projected finish, as of today")
pool = queries.player_pool(ctx.league_id, ctx.version)
if pool.empty:
    st.info("The projection appears after the next morning's data refresh.")
else:
    with st.expander("Injury assumptions"):
        st.caption(
            "Injured players are left out of the weeks they're expected to miss, then "
            "count in full. ESPN's return date is used when it has one; otherwise these "
            "defaults, counted from the current week."
        )
        a1, a2, a3 = st.columns(3)
        ir_weeks = a1.number_input("In the IR slot: weeks out", 0, 20, 4)
        out_weeks = a2.number_input("Out: weeks out", 0, 20, 2)
        dtd_weeks = a3.number_input("Day-to-day: weeks out", 0, 20, 1)
    rules = InjuryRules(day_to_day_weeks=dtd_weeks, out_weeks=out_weeks, ir_weeks=ir_weeks)

    current, last_week = ctx.current_week, ctx.last_week
    as_of = ctx.doc["last_ingested_at"].date()
    teams = ctx.team_names
    lines = per_game_lines(pool)
    proj = project_season(
        lines,
        queries.all_play(ctx.league_id, ctx.version),
        ctx.cats,
        current,
        last_week,
        as_of,
        rules,
        teams.index,
        ctx.each_category,
    )
    proj = proj.assign(team_name=proj["team_id"].map(teams)).sort_values(
        ["projected_rank", "team_name"]
    )

    played = int(proj["weeks_played"].max())
    if played:
        how = (
            f"Weeks 1-{played} use what actually happened. Weeks {current}-{last_week} are "
            "projected"
        )
    else:
        how = f"No weeks are finished yet, so all {last_week} are projected"
    st.caption(
        f"{how} from today's rosters: each available player's per-game averages (his "
        "season averages, or ESPN's projection until he's played), compared team against "
        f"team on the league's {len(ctx.cats)} categories, week by week as injured players "
        "return."
        + (" Records count categories, as Each Category scores." if ctx.each_category else "")
    )
    proj = proj.assign(
        so_far=record(proj["actual_wins"], proj["actual_losses"], proj["actual_ties"]),
        rest=record(proj["proj_wins"], proj["proj_losses"], proj["proj_ties"]),
        per_week=[
            f"{lo:g}" if lo == hi else f"{lo:g}-{hi:g}"
            for lo, hi in zip(proj["week_min_wins"], proj["week_max_wins"], strict=True)
        ],
        final=record(proj["final_wins"], proj["final_losses"], proj["final_ties"]),
    )
    columns = [
        "projected_rank", "team_name", "so_far", "rest", "per_week", "missing_now", "final",
        "final_win_pct",
    ]  # fmt: skip
    if not played:  # nothing to add yet: the rest of the season is the final record
        columns.remove("so_far")
        columns.remove("rest")
    st.dataframe(
        proj[columns],
        column_config={
            "projected_rank": st.column_config.NumberColumn("#", width="small"),
            "team_name": "Team",
            "so_far": st.column_config.TextColumn(
                "So far", help=f"Actual all-play record, weeks 1-{played}"
            ),
            "rest": st.column_config.TextColumn(
                "Rest of season", help=f"Projected all-play record, weeks {current}-{last_week}"
            ),
            "per_week": st.column_config.TextColumn(
                "Wins per week",
                help="Projected all-play wins in a remaining week (of "
                f"{(len(teams) - 1) * (len(ctx.cats) if ctx.each_category else 1)}): a range "
                "when injured players are due back partway through",
            ),
            "missing_now": st.column_config.NumberColumn(
                "Injured now", help="Players expected to miss the current week"
            ),
            "final": st.column_config.TextColumn(
                "Projected final", help=f"All-play record through week {last_week}"
            ),
            "final_win_pct": st.column_config.NumberColumn("Final win %", format="%.3f"),
        },
        hide_index=True,
        width="stretch",
        height=ui.table_height(len(proj)),
    )

    missing = availability(lines, current, as_of, rules)
    missing = missing.loc[missing["back_in_week"] > current].sort_values(
        ["back_in_week", "player_name"], ascending=[False, True]
    )
    with st.expander(f"Who's missing ({len(missing)} players)"):
        if missing.empty:
            st.write("Nobody is expected to miss time.")
        else:
            st.dataframe(
                missing.assign(
                    team=missing["team_id"].map(teams),
                    back=[
                        f"Week {w}" if w <= last_week else "After the regular season"
                        for w in missing["back_in_week"]
                    ],
                )[["player_name", "team", "reason", "back"]],
                column_config={
                    "player_name": "Player",
                    "team": "Team",
                    "reason": "Based on",
                    "back": "Counts again from",
                },
                hide_index=True,
                width="stretch",
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
