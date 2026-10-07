"""Roster Strength page (Step 6), two tabs:

* Category rankings -- every team ranked 1-14 in every category, through two lenses:
  roster strength (team z totals per stat window, forward-looking) and results
  (finished weeks). The highlighted team's row is outlined and carries its tiers
  (Lock / Swing / Punt). Below: one category's values for every team, so the gaps
  that ranks hide are visible. Reads v_category_ranks; tiers from app/analysis.
* Per-game totals -- the team x category heatmap of combined per-game stats.
  Reads v_roster_strength.
"""

import plotly.graph_objects as go
import streamlit as st

import analyzer
import login
import queries
import ui
from analysis.weights import compute_weights
from categories import COLUMNS, LABELS, fmt

st.title("Roster Strength")
rankings_tab, totals_tab = st.tabs(["Category rankings", "Per-game totals"])


def rank_scale() -> list[list]:
    """Rank 1 (best) blue, through gray, to last place red."""
    c = ui.colors()
    return [[0.0, c["positive"]], [0.5, c["midpoint"]], [1.0, c["negative"]]]


def category_rankings() -> None:
    ranks = queries.category_ranks()
    names = analyzer.team_names()
    if ranks.empty:
        st.info("No ranking data yet.")
        return

    c1, c2, c3 = st.columns([1.2, 1.2, 1.6])
    lens = c1.segmented_control(
        "Lens",
        ["roster", "results"],
        default="roster",
        format_func={"roster": "Roster strength", "results": "Results"}.get,
        required=True,
    )
    window = None
    if lens == "roster":
        windows = analyzer.available_windows()
        window = c2.selectbox("Stats from", windows, format_func=analyzer.STAT_WINDOWS.get)
    team_ids = list(names.index)
    me = c3.selectbox(
        "Highlight",
        team_ids,
        index=team_ids.index(login.my_team()) if login.my_team() in team_ids else 0,
        format_func=names.get,
    )

    rows = ranks.loc[ranks["lens"] == lens]
    if lens == "roster":
        rows = rows.loc[rows["stat_window"] == window]
        st.caption(
            "Each team's players' z-scores added up per category (IR excluded): where "
            "the roster stands, before or during the season. Rank 1 is best."
        )
    else:
        st.caption(
            "What actually happened in finished weeks: average weekly totals, with "
            "percentages from total makes over total attempts. Rank 1 is best."
        )
    if rows.empty:
        st.info("Results rankings appear once week 1 has finished.")
        return

    grid = rows.pivot(index="team_id", columns="category", values="rank")[COLUMNS]
    values = rows.pivot(index="team_id", columns="category", values="value")[COLUMNS]
    grid["avg"] = grid.mean(axis=1)

    sort_options = ["avg", *COLUMNS]
    sort_by = st.selectbox(
        "Sort by",
        sort_options,
        format_func=lambda col: "Average rank" if col == "avg" else LABELS[col],
    )
    order = grid.sort_values([sort_by, "avg"], ascending=False).index  # best ends on top

    tiers = None
    if lens == "roster":
        _, totals = analyzer.league(window)
        if me in totals.index:
            tiers = compute_weights(totals, me)["tier"]

    def cell(team, col):
        if col == "avg":
            return f"{grid.at[team, 'avg']:.1f}"
        text = str(int(grid.at[team, col]))
        if tiers is not None and team == me:
            text += f" {tiers[col][0]}"  # L / S / P badge
        return text

    def hover(team, col):
        if col == "avg":
            return f"Average rank {grid.at[team, 'avg']:.1f}"
        value = values.at[team, col]
        shown = f"{value:+.2f} z" if lens == "roster" else fmt(col, value)
        line = f"{LABELS[col]}: rank {int(grid.at[team, col])} · {shown}"
        if tiers is not None and team == me:
            line += f" · {tiers[col]}"
        return line

    columns = [*COLUMNS, "avg"]
    fig = go.Figure(
        go.Heatmap(
            z=[[grid.at[t, col] for col in columns] for t in order],
            x=[LABELS[col] for col in COLUMNS] + ["Avg rank"],
            y=[names.get(t, str(t)) for t in order],
            text=[[cell(t, col) for col in columns] for t in order],
            customdata=[[hover(t, col) for col in columns] for t in order],
            texttemplate="%{text}",
            textfont={"size": 11},
            colorscale=rank_scale(),
            zmin=1,
            zmax=len(grid),
            xgap=2,
            ygap=2,
            showscale=False,
            hovertemplate="<b>%{y}</b><br>%{customdata}<extra></extra>",
        )
    )
    row = list(order).index(me) if me in order else None
    if row is not None:
        fig.add_shape(
            type="rect",
            x0=-0.5,
            x1=len(columns) - 0.5,
            y0=row - 0.5,
            y1=row + 0.5,
            line={"color": ui.colors()["series"][1], "width": 3},
        )
    fig.update_xaxes(side="top")
    ui.show(ui.style(fig, height=34 * len(grid) + 90))
    if tiers is not None:
        st.caption(
            f"{names[me]}'s cells show its tier: **L** Lock (comfortably ahead), "
            "**S** Swing (a small gain flips matchups), **P** Punt (out of reach). "
            "Change them on the Trade Analyzer page."
        )

    st.subheader("Category detail")
    category = st.selectbox("Category", COLUMNS, format_func=LABELS.get)
    detail = values[category].dropna().sort_values()
    c = ui.colors()
    bar = go.Figure(
        go.Bar(
            x=detail.to_numpy(),
            y=[names.get(t, str(t)) for t in detail.index],
            orientation="h",
            marker={
                "color": [c["series"][0] if t == me else c["muted"] for t in detail.index],
                "cornerradius": 4,
            },
            text=[f"{v:+.2f}" if lens == "roster" else fmt(category, v) for v in detail],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{y}: %{text}<extra></extra>",
        )
    )
    unit = "team z (sum of player z-scores)" if lens == "roster" else LABELS[category]
    # Room past both ends for the value labels, which sit outside the bars -- without
    # it they're cut off at the edge, or collide with team names on a phone.
    low, high = min(float(detail.min()), 0.0), max(float(detail.max()), 0.0)
    pad = 0.3 * (high - low or 1.0)
    bar.update_xaxes(title=unit, zeroline=True, range=[low - (pad if low < 0 else 0), high + pad])
    bar.update_layout(bargap=0.25)
    ui.show(ui.style(bar, height=30 * len(detail) + 90))
    if lens == "results":
        win_rates = rows.loc[rows["category"] == category].set_index("team_id")["win_rate"]
        st.caption(
            f"All-play win rate in {LABELS[category]} for {names[me]}: "
            f"{win_rates.get(me, float('nan')):.0%} of other teams beaten per week."
        )


def per_game_totals() -> None:
    st.caption(
        "Each roster's combined per-game stats (IR excluded), compared with the league. "
        "Blue is above average, red below; the number is the roster's actual value."
    )
    strength = queries.roster_strength()
    if strength.empty:
        st.info("No roster data yet.")
        return

    windows = {
        "last_7": "Last 7 days",
        "last_15": "Last 15 days",
        "last_30": "Last 30 days",
        "season": "Season",
        "projected": "Projected",
    }
    available = [w for w in windows if w in set(strength["stat_window"])]
    window = st.segmented_control(
        "Stats from",
        available,
        default="last_15" if "last_15" in available else available[0],
        format_func=windows.get,
        required=True,
        key="per-game-window",
    )
    if "last_15" not in available:
        st.caption("Recent-form windows appear once games have been played.")

    rows = strength.loc[strength["stat_window"] == window].copy()
    rows["overall"] = rows[[f"{col}_z" for col in COLUMNS]].mean(axis=1)
    rows = rows.sort_values("overall")  # Plotly draws the first row at the bottom

    z = rows[[f"{col}_z" for col in COLUMNS]].to_numpy()
    text = [
        [fmt(col, v) for col, v in zip(COLUMNS, r, strict=True)] for r in rows[COLUMNS].to_numpy()
    ]
    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=[LABELS[col] for col in COLUMNS],
            y=rows["team_name"],
            text=text,
            texttemplate="%{text}",
            textfont={"size": 11},
            colorscale=ui.diverging_scale(),
            zmid=0,
            zmin=-2.5,
            zmax=2.5,
            xgap=2,
            ygap=2,
            colorbar={"title": "SD", "thickness": 10, "tickformat": "+.0f"},
            hovertemplate="<b>%{y}</b><br>%{x}: %{text} (%{z:+.2f} SD)<extra></extra>",
        )
    )
    fig.update_xaxes(side="top")
    ui.show(ui.style(fig, height=36 * len(rows) + 80))

    with st.expander("Table view"):
        table = rows.sort_values("overall", ascending=False)
        st.dataframe(
            table[["team_name", "players", *COLUMNS]],
            column_config={
                "team_name": "Team",
                "players": st.column_config.NumberColumn("Players", width="small"),
                **{
                    col: st.column_config.NumberColumn(
                        LABELS[col], format="%.3f" if col.endswith("_pct") else "%.1f"
                    )
                    for col in COLUMNS
                },
            },
            hide_index=True,
            width="stretch",
        )


with rankings_tab:
    category_rankings()
with totals_tab:
    per_game_totals()
