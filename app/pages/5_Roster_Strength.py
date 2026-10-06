"""Roster Strength page, two tabs:

* Category rankings -- every team ranked in every one of the league's categories,
  through two lenses: roster strength (team z totals per stat window, forward-looking) and results
  (finished weeks). The highlighted team's row is outlined and carries its tiers
  (Lock / Swing / Punt). Below: one category's values for every team, so the gaps
  that ranks hide are visible. Reads m_category_ranks; tiers from app/analysis.
* Per-game totals -- the team x category heatmap of combined per-game stats.
  Reads m_roster_strength. Lower-is-better categories (turnovers) rank and shade
  the right way round: fewest is rank 1 and blue.
"""

import plotly.graph_objects as go
import streamlit as st

import analyzer
import league
import queries
import ui
from analysis.weights import compute_weights
from categories import by_key, fmt, keys

st.title("Roster Strength")
ctx = league.current()
COLUMNS = keys(ctx.cats)
CATS = by_key(ctx.cats)
rankings_tab, totals_tab = st.tabs(["Category rankings", "Per-game totals"])


def rank_scale() -> list[list]:
    """Rank 1 (best) blue, through gray, to last place red."""
    c = ui.colors()
    return [[0.0, c["positive"]], [0.5, c["midpoint"]], [1.0, c["negative"]]]


def category_rankings() -> None:
    ranks = queries.category_ranks(ctx.league_id, ctx.version)
    names = ctx.team_names
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
        windows = analyzer.available_windows(ctx.league_id, ctx.version)
        window = c2.selectbox("Stats from", windows, format_func=analyzer.STAT_WINDOWS.get)
    team_ids = list(names.index)
    me = c3.selectbox(
        "Highlight",
        team_ids,
        index=team_ids.index(ctx.my_team) if ctx.my_team in team_ids else 0,
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
            "percentages from season totals. Rank 1 is best (fewest, where lower wins)."
        )
    if rows.empty:
        st.info("Results rankings appear once week 1 has finished.")
        return

    grid = rows.pivot(index="team_id", columns="category", values="rank").reindex(columns=COLUMNS)
    values = rows.pivot(index="team_id", columns="category", values="value").reindex(
        columns=COLUMNS
    )
    grid["avg"] = grid.mean(axis=1)

    sort_options = ["avg", *COLUMNS]
    sort_by = st.selectbox(
        "Sort by",
        sort_options,
        format_func=lambda col: "Average rank" if col == "avg" else col,
    )
    order = grid.sort_values([sort_by, "avg"], ascending=False).index  # best ends on top

    tiers = None
    if lens == "roster":
        _, totals = analyzer.league(ctx.league_id, ctx.version, window)
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
        shown = f"{value:+.2f} z" if lens == "roster" else fmt(CATS[col], value)
        line = f"{col}: rank {int(grid.at[team, col])} · {shown}"
        if tiers is not None and team == me:
            line += f" · {tiers[col]}"
        return line

    columns = [*COLUMNS, "avg"]
    fig = go.Figure(
        go.Heatmap(
            z=[[grid.at[t, col] for col in columns] for t in order],
            x=[*COLUMNS, "Avg rank"],
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
    category = st.selectbox("Category", COLUMNS)
    cat = CATS[category]
    # Best ends on top: Plotly draws the first bar at the bottom.
    detail = (
        values[category]
        .dropna()
        .sort_values(ascending=not (cat.lower_is_better and lens == "results"))
    )
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
            text=[f"{v:+.2f}" if lens == "roster" else fmt(cat, v) for v in detail],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{y}: %{text}<extra></extra>",
        )
    )
    unit = (
        "team z (sum of player z-scores)"
        if lens == "roster"
        else category + (" (lower wins)" if cat.lower_is_better else "")
    )
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
            f"All-play win rate in {category} for {names[me]}: "
            f"{win_rates.get(me, float('nan')):.0%} of other teams beaten per week."
        )


def per_game_totals() -> None:
    st.caption(
        "Each roster's combined per-game stats (IR excluded), compared with the league. "
        "Blue is above average, red below; the number is the roster's actual value."
    )
    strength = queries.roster_strength(ctx.league_id, ctx.version)
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

    long = strength.loc[strength["stat_window"] == window]
    value = long.pivot_table(index="team_id", columns="category", values="value").reindex(
        columns=COLUMNS
    )
    zs = long.pivot_table(index="team_id", columns="category", values="z").reindex(columns=COLUMNS)
    players = long.groupby("team_id")["players"].max()
    order = zs.mean(axis=1).sort_values().index  # Plotly draws the first row at the bottom
    value, zs = value.loc[order], zs.loc[order]

    text = [[fmt(CATS[c], v) for c, v in zip(COLUMNS, r, strict=True)] for r in value.to_numpy()]
    fig = go.Figure(
        go.Heatmap(
            z=zs.to_numpy(),
            x=COLUMNS,
            y=[ctx.team_names.get(t, str(t)) for t in order],
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
    ui.show(ui.style(fig, height=36 * len(order) + 80))

    with st.expander("Table view"):
        best_first = list(order)[::-1]
        st.dataframe(
            {
                "Team": [ctx.team_names.get(t, str(t)) for t in best_first],
                "Players": [int(players.get(t, 0)) for t in best_first],
                **{c: [fmt(CATS[c], value.at[t, c]) for t in best_first] for c in COLUMNS},
            },
            hide_index=True,
            width="stretch",
        )


with rankings_tab:
    category_rankings()
with totals_tab:
    per_game_totals()
