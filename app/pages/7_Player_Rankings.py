"""Player Rankings page: every pool player -- all rostered players plus the top free
agents -- ranked in each of the league's categories and overall, shaded like the team
Category rankings (rank 1 blue, last red). Ranks are league-wide (among the whole
pool), so filtering to one team still shows where its players stand overall. Reads
m_player_z; ranking math in app/analysis/rankings.py.
"""

import pandas as pd
import streamlit as st

import analyzer
import league
import queries
import ui
from analysis.rankings import player_rankings
from categories import fmt, keys

st.title("Player Rankings")
ctx = league.current()
COLUMNS = keys(ctx.cats)

z = queries.player_z(ctx.league_id, ctx.version)
windows = analyzer.available_windows(ctx.league_id, ctx.version)
if z.empty or not windows:
    st.info("No player data yet.")
    st.stop()
names = ctx.team_names

c1, c2, c3 = st.columns([1, 1.3, 1.5])
window = c1.selectbox("Stats from", windows, format_func=analyzer.STAT_WINDOWS.get)
mine = ctx.my_team
team_choices = [
    "all",
    *(["mine"] if mine is not None else []),
    "free",
    *[int(t) for t in names.index],
]
team_label = {
    "all": "All players",
    "mine": f"My team ({names.get(mine, '')})",
    "free": "Free agents",
}
team = c2.selectbox(
    "Players", team_choices, format_func=lambda t: team_label.get(t) or names.get(t, str(t))
)
show = c3.segmented_control(
    "Show",
    ["rank", "value", "z"],
    default="rank",
    format_func={"rank": "Ranks", "value": "Per game", "z": "Z-scores"}.get,
    required=True,
)

ranks = player_rankings(z.loc[z["stat_window"] == window])
pool_size = len(ranks)

f1, f2, f3 = st.columns([1.4, 1.2, 1])
search = f1.text_input("Find a player", placeholder="Name")
positions = sorted(p for p in ranks["position"].dropna().unique() if p)
picked_positions = f2.multiselect("Positions", positions, placeholder="All")
healthy_only = f3.checkbox("Hide injured", help="Hide players listed Out or in an IR slot")

shown = ranks
if team == "mine":
    shown = shown.loc[shown["team_id"] == mine]
elif team == "free":
    shown = shown.loc[shown["is_free_agent"]]
elif team != "all":
    shown = shown.loc[shown["team_id"] == team]
if search.strip():
    shown = shown.loc[shown["player_name"].str.contains(search.strip(), case=False, regex=False)]
if picked_positions:
    shown = shown.loc[shown["position"].isin(picked_positions)]
if healthy_only:
    shown = shown.loc[~shown["is_ir"] & (shown["injury_status"] != "OUT")]

st.caption(
    f"Showing {len(shown)} of {pool_size} players. Ranks are among all {pool_size} "
    "(every rostered player plus the top free agents): blue is near the top, red near "
    f"the bottom. Overall adds up a player's {len(COLUMNS)} category z-scores (lower-is-better "
    "categories flipped, so fewer turnovers rank higher). Click a column to sort."
)
if shown.empty:
    st.info("No players match these filters.")
    st.stop()

STATUS = {"ACTIVE": "", "DAY_TO_DAY": "Day-to-day", "OUT": "Out"}
table = pd.DataFrame(
    {
        # The shaded grid first, so it's what you see on a phone; details last.
        "Player": shown["player_name"],
        "Overall": shown["overall_rank"],
        **{c: shown[f"{c}_{show}"] for c in COLUMNS},
        "Team": [
            "Free agent" if fa else names.get(int(t), "") if pd.notna(t) else ""
            for t, fa in zip(shown["team_id"], shown["is_free_agent"], strict=True)
        ],
        "Pos": shown["position"].fillna(""),
        "Health": [
            "IR" if ir else STATUS.get(s, str(s).replace("_", " ").title())
            for ir, s in zip(shown["is_ir"], shown["injury_status"].fillna("ACTIVE"), strict=True)
        ],
    }
)
rank_lookup = {c: shown[f"{c}_rank"].to_numpy() for c in COLUMNS}
rank_lookup["Overall"] = shown["overall_rank"].to_numpy()


def shade(column: pd.Series) -> list[str]:
    """Shade a category (or Overall) column by the player's rank, whatever is shown."""
    if column.name not in rank_lookup:
        return [""] * len(column)
    return [ui.rank_cell_style(r, pool_size) for r in rank_lookup[column.name]]


formats = (
    {c.key: (lambda v, c=c: fmt(c, v)) for c in ctx.cats}
    if show == "value"
    else ({c: "{:+.2f}" for c in COLUMNS} if show == "z" else {})
)
styled = table.style.apply(shade, axis=0).format(formats, na_rep="–")
st.dataframe(
    styled,
    hide_index=True,
    width="stretch",
    height=ui.table_height(min(len(table), 20)),
    column_config={
        "Overall": st.column_config.NumberColumn(width="small", help="Rank by total z-score"),
        "Player": st.column_config.TextColumn(pinned=True),
    },
)
