"""Trade Analyzer page (Step 6, added after the original proposal): pick "your team"
and a trade partner from the league; pick players from each roster by clicking their
row, which moves them into the selected-to-trade section below (click again to
remove). Shows both sides' per-game category totals before the trade, after the
trade, and the delta. Reads v_team_roster_stats. The before/after/delta math runs
in trade.py, not in SQL -- the one page where that's deliberate, since the player
selection is arbitrary and can't be precomputed.
"""

import pandas as pd
import streamlit as st

import queries
import ui
from categories import COLUMNS, LABELS, fmt
from trade import trade_impact

st.title("Trade Analyzer")
st.caption(
    "Pick two teams, then click players in each roster to put them in the trade. "
    "Click a player again to take them back out."
)

players = queries.team_roster_stats()
if players.empty:
    st.info("No roster data yet.")
    st.stop()

WINDOWS = {
    "season": "Season",
    "last_30": "Last 30 days",
    "last_15": "Last 15 days",
    "last_7": "Last 7 days",
    "projected": "Projected",
}
available = [w for w in WINDOWS if w in set(players["stat_window"])]
names = players.drop_duplicates("team_id").set_index("team_id")["team_name"].sort_values()

c1, c2 = st.columns(2)
mine = c1.selectbox("Your team", names.index, format_func=names.get)
theirs = c2.selectbox("Trade partner", [t for t in names.index if t != mine], format_func=names.get)
window = st.segmented_control(
    "Stats from", available, default=available[0], format_func=WINDOWS.get, required=True
)

in_window = players.loc[players["stat_window"] == window]
ROSTER_COLUMNS = ["player_name", "position", "lineup_slot", *COLUMNS]
ROSTER_CONFIG = {
    "player_name": "Player",
    "position": st.column_config.TextColumn("Pos", width="small"),
    "lineup_slot": st.column_config.TextColumn("Slot", width="small"),
    **{
        col: st.column_config.NumberColumn(
            LABELS[col], format="%.3f" if col.endswith("_pct") else "%.1f"
        )
        for col in COLUMNS
    },
}


def pick_players(team_id: int, column) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Shows a roster; returns it and the rows the user has clicked."""
    roster = (
        in_window.loc[in_window["team_id"] == team_id]
        .sort_values("pts", ascending=False)
        .reset_index(drop=True)
    )
    with column:
        st.markdown(f"**{names[team_id]}**")
        event = st.dataframe(
            roster[ROSTER_COLUMNS],
            column_config=ROSTER_CONFIG,
            hide_index=True,
            height=ui.table_height(len(roster)),
            on_select="rerun",
            selection_mode="multi-row",
            # Keyed per team and window, so switching either starts a fresh pick.
            key=f"roster-{team_id}-{window}",
        )
    return roster, roster.iloc[event.selection.rows]


r1, r2 = st.columns(2)
my_roster, my_out = pick_players(mine, r1)
their_roster, their_out = pick_players(theirs, r2)

st.subheader("The trade")
if my_out.empty and their_out.empty:
    st.info("No players selected yet.")
    st.stop()

s1, s2 = st.columns(2)
s1.markdown(f"**{names[mine]} send**")
s1.write(", ".join(my_out["player_name"]) or "Nobody")
s2.markdown(f"**{names[theirs]} send**")
s2.write(", ".join(their_out["player_name"]) or "Nobody")

c = ui.colors()


def delta_cell(col: str, value: float) -> str:
    if pd.isna(value) or abs(value) < 1e-9:
        return "–"
    text = f"{value:+.3f}".replace("0.", ".") if col.endswith("_pct") else f"{value:+.1f}"
    return f"▲ {text}" if value > 0 else f"▼ {text}"


def impact_table(roster, sending, receiving) -> None:
    impact = trade_impact(roster, sending["player_id"].tolist(), receiving)
    table = pd.DataFrame(
        {
            "Category": [LABELS[col] for col in COLUMNS],
            "Before": [fmt(col, impact.at[col, "before"]) for col in COLUMNS],
            "After": [fmt(col, impact.at[col, "after"]) for col in COLUMNS],
            "Change": [delta_cell(col, impact.at[col, "delta"]) for col in COLUMNS],
        }
    )

    def color(cell: str) -> str:
        if cell.startswith("▲"):
            return f"color: {c['up']}"
        if cell.startswith("▼"):
            return f"color: {c['down']}"
        return ""

    st.dataframe(table.style.map(color, subset=["Change"]), hide_index=True, width="stretch")
    gained = int((impact["delta"] > 1e-9).sum())
    lost = int((impact["delta"] < -1e-9).sum())
    noun = "category" if gained == 1 else "categories"
    st.caption(f"Better in {gained} {noun}, worse in {lost}.")


st.caption("Per-game roster totals, IR excluded. ▲ is better in every category.")
h1, h2 = st.columns(2)
with h1:
    st.markdown(f"**{names[mine]}**")
    impact_table(my_roster, my_out, their_out)
with h2:
    st.markdown(f"**{names[theirs]}**")
    impact_table(their_roster, their_out, my_out)
