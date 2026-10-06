"""Compare page (Step 6, Players mode added later): a Teams | Players toggle.

Teams: pick two teams + week or season; radar chart of category z-scores and
side-by-side bars per category. Reads v_team_week_cats; the z-scores are computed
in compare.py because the period is chosen on this page.

Players: pick 2-4 players (rostered or free agent) and a stat window; the same
z-scores and ranks Player Rankings shows (v_player_z, v_player_pool), a radar or
(on a narrow screen) grouped bars, a stat table, each player's fit for the
signed-in manager's team, a recent-form line chart, and health/durability (the
same component the Mock trade's "Players in this deal" table uses). Player
Rankings and the Trade Analyzer can open this page with players already picked
(st.session_state["compare-players"]); the picker and mode both keep their state
across a mode toggle or a reload, via st.session_state.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import analyzer
import login
import queries
import ui
from analysis.weights import player_fit as fit_from_weights
from categories import CATEGORIES, COLUMNS, LABELS, PCT_PARTS, fmt
from compare import (
    POSITIONS,
    baseline_id,
    head_to_head,
    head_to_head_verdict,
    period_lines,
    player_compare_frame,
    pool_window_frame,
    position_baseline,
    season_totals,
    starter_ids,
    zscores,
)
from health import games_by_season_text, health_text


def sticky_default(key: str, default) -> None:
    """Call before a selectbox/segmented_control/pills widget living inside the
    Teams/Players if-else: Streamlit clears those widgets' session_state for any
    run where their branch doesn't execute (confirmed empirically; st.multiselect
    isn't affected, so compare-picker needs no such help), so a plain toggle away
    and back would otherwise reset it to `default`. A separate "-backup" key, which
    always runs every pass regardless of branch, remembers the last real value."""
    if key not in st.session_state:
        st.session_state[key] = st.session_state.get(f"{key}-backup", default)


def sticky_save(key: str, value) -> None:
    st.session_state[f"{key}-backup"] = value


st.title("Compare")

# A Player Rankings / Trade Analyzer button can hand off players to compare here.
st.session_state.setdefault("compare-mode", "Teams")
incoming = st.session_state.pop("compare-players", None)
if incoming:
    st.session_state["compare-mode"] = "Players"
    st.session_state["compare-picker"] = list(incoming)[:4]

mode = st.segmented_control("Mode", ["Teams", "Players"], key="compare-mode")

if mode == "Teams":
    weeks = queries.team_week_cats()
    names = queries.teams().set_index("team_id")["team_name"]
    if weeks.empty:
        st.info("No matchup data yet.")
        st.stop()

    team_ids = sorted(weeks["team_id"].unique(), key=lambda t: names.get(t, ""))
    week_options = ["Season", *sorted(weeks["matchup_period"].unique(), reverse=True)]

    c1, c2, c3 = st.columns([2, 2, 1])
    mine = login.my_team()
    sticky_default("compare-team-a", mine if mine in team_ids else team_ids[0])
    if st.session_state["compare-team-a"] not in team_ids:
        st.session_state["compare-team-a"] = team_ids[0]
    a = c1.selectbox("Team", team_ids, format_func=names.get, key="compare-team-a")
    sticky_save("compare-team-a", a)

    b_options = [t for t in team_ids if t != a]
    sticky_default("compare-team-b", b_options[0])
    if st.session_state["compare-team-b"] not in b_options:
        st.session_state["compare-team-b"] = b_options[0]
    b = c2.selectbox("Against", b_options, format_func=names.get, key="compare-team-b")
    sticky_save("compare-team-b", b)

    sticky_default("compare-period", week_options[0])
    if st.session_state["compare-period"] not in week_options:
        st.session_state["compare-period"] = week_options[0]
    period = c3.selectbox(
        "Period", week_options, format_func=lambda w: w if w == "Season" else f"Week {w}",
        key="compare-period",
    )  # fmt: skip
    sticky_save("compare-period", period)

    lines = period_lines(weeks, None if period == "Season" else int(period))
    z = zscores(lines)
    wins, losses, ties = head_to_head(lines.loc[a], lines.loc[b])
    verdict = "beat" if wins > losses else "lose to" if wins < losses else "tie"
    when = "on season averages" if period == "Season" else f"in week {period}"
    st.markdown(
        f"**{names[a]}** would {verdict} **{names[b]}** {when}, "
        f"winning {wins}, losing {losses} and tying {ties} of the 9 categories."
    )

    c = ui.colors()
    pair = [(a, c["series"][0]), (b, c["series"][1])]

    if z.loc[[a, b]].isna().all().all():
        st.info("Every team is level in every category so far, so there's nothing to chart yet.")
    else:
        st.subheader("Category profile")
        st.caption("Standard deviations above (+) or below (−) the league average.")
        radar = go.Figure()
        theta = [LABELS[col] for col in COLUMNS] + [LABELS[COLUMNS[0]]]
        for team, color in pair:
            r = z.loc[team, COLUMNS].fillna(0).tolist()
            radar.add_trace(
                go.Scatterpolar(
                    r=r + r[:1],
                    theta=theta,
                    name=names[team],
                    line={"color": color, "width": 2},
                    marker={"size": 8},
                    hovertemplate="%{theta}: %{r:+.2f} SD<extra>" + names[team] + "</extra>",
                )
            )
        span = max(2.0, float(z.loc[[a, b]].abs().max().max()) + 0.25)
        # The center is -span, not 0, so mark where "league average" sits.
        radar.add_trace(
            go.Scatterpolar(
                r=[0] * len(theta),
                theta=theta,
                mode="lines",
                name="League average",
                line={"color": c["muted"], "width": 1, "dash": "dot"},
                hoverinfo="skip",
            )
        )
        radar.update_layout(
            polar={
                "bgcolor": "rgba(0,0,0,0)",
                "radialaxis": {
                    "range": [-span, span],
                    "showticklabels": False,
                    "gridcolor": c["grid"],
                },  # fmt: skip
                "angularaxis": {"gridcolor": c["grid"], "linecolor": c["grid"]},
            }
        )
        ui.show(ui.style(radar, height=420))

    st.subheader("By category")
    bars = make_subplots(rows=3, cols=3, subplot_titles=[cat.label for cat in CATEGORIES])
    for i, cat in enumerate(CATEGORIES):
        for team, color in pair:
            value = lines.loc[team, cat.column]
            bars.add_trace(
                go.Bar(
                    x=[names[team]],
                    y=[value],
                    marker={"color": color, "cornerradius": 4},
                    name=names[team],
                    showlegend=i == 0,
                    text=[fmt(cat.column, value)],
                    textposition="outside",
                    cliponaxis=False,
                    hovertemplate=f"{cat.label}: %{{text}}<extra>{names[team]}</extra>",
                ),
                row=i // 3 + 1,
                col=i % 3 + 1,
            )
    bars.update_xaxes(showticklabels=False)
    bars.update_yaxes(showticklabels=False, showgrid=False, rangemode="tozero")
    bars.update_layout(bargap=0.15)
    ui.style(bars, height=560).update_layout(margin={"t": 72}, legend={"y": 1.1})
    ui.show(bars)

    with st.expander("Table view"):
        table = lines.loc[[a, b], COLUMNS].T
        st.dataframe(
            table.apply(lambda row: [fmt(row.name, v) for v in row], axis=1, result_type="expand")
            .set_axis([names[a], names[b]], axis=1)
            .set_axis([LABELS[col] for col in COLUMNS], axis=0),
            width="stretch",
        )

else:  # Players
    z_all = queries.player_z()
    pool_all = queries.player_pool()
    windows = analyzer.available_windows()
    if z_all.empty or not windows:
        st.info("No player data yet.")
        st.stop()
    names = analyzer.team_names()
    mine = login.my_team()

    p1, p2 = st.columns([1, 2])
    sticky_default("compare-window", windows[0])
    if st.session_state["compare-window"] not in windows:
        st.session_state["compare-window"] = windows[0]
    window = p1.selectbox(
        "Stats from", windows, format_func=analyzer.STAT_WINDOWS.get, key="compare-window"
    )
    sticky_save("compare-window", window)

    sticky_default("compare-filter-chips", ["My team", "Other teams", "Free agents"])
    filter_chips = p2.pills(
        "Filter picker by",
        ["My team", "Other teams", "Free agents"],
        selection_mode="multi",
        key="compare-filter-chips",
    )
    sticky_save("compare-filter-chips", filter_chips)

    z_window = z_all.loc[z_all["stat_window"] == window]
    pool_window = pool_window_frame(pool_all, window)
    if z_window.empty:
        st.info("No player data for this stat window yet.")
        st.stop()
    info = z_window.drop_duplicates("player_id").set_index("player_id")

    def in_filter(row) -> bool:
        if row["is_free_agent"]:
            return "Free agents" in (filter_chips or [])
        if row["team_id"] == mine:
            return "My team" in (filter_chips or [])
        return "Other teams" in (filter_chips or [])

    eligible = info.loc[info.apply(in_filter, axis=1)] if filter_chips else info.iloc[0:0]

    def picker_label(pid) -> str:
        row = info.loc[pid]
        team = "FA" if row["is_free_agent"] else names.get(int(row["team_id"]), "")
        badge = ""
        if row["is_ir"]:
            badge = " · IR"
        elif row["injury_status"] == "OUT":
            badge = " · Out"
        elif row["injury_status"] == "DAY_TO_DAY":
            badge = " · Day-to-day"
        return f"{row['player_name']} · {row['position'] or '–'} · {team}{badge}"

    picked = st.multiselect(
        "Players",
        [int(i) for i in eligible.index],
        format_func=picker_label,
        max_selections=4,
        key="compare-picker",
        placeholder="Type a player's name...",
        help="Up to 4 players, rostered or free agent. Narrow the list with the chips above.",
    )

    o1, o2 = st.columns(2)
    sticky_default("compare-baseline", None)
    baseline_pos = o1.selectbox(
        "Compare against",
        [None, *POSITIONS],
        format_func=lambda p: "No position baseline" if p is None else f"Average starting {p}",
        key="compare-baseline",
        help="The average of every rostered player at that position in an active "
        "lineup slot (not bench or IR) -- a typical starter to measure against.",
    )
    sticky_save("compare-baseline", baseline_pos)
    sticky_default("compare-basis", "Per game")
    basis = o2.segmented_control(
        "Show",
        ["Per game", "Season totals"],
        key="compare-basis",
        required=True,
        help="Season totals: per-game stats times games played in this window (projected "
        "games for Projected), so a player who plays 70 games counts for more than one "
        "who plays 40.",
    )
    sticky_save("compare-basis", basis)
    use_totals = basis == "Season totals"

    entities = list(picked)
    groups: dict[int, list[int]] = {}
    pname = {pid: info.loc[pid, "player_name"] if pid in info.index else str(pid) for pid in picked}
    if baseline_pos:
        members = starter_ids(z_all, window, baseline_pos)
        if members:
            bid = baseline_id(baseline_pos)
            entities.append(bid)
            groups[bid] = members
            pname[bid] = f"Avg starting {baseline_pos}"
        else:
            st.caption(f"No starting {baseline_pos}s in this stat window.")
    if len(entities) < 2:
        st.info("Pick 2-4 players, or 1 player and a position baseline.")
        st.stop()

    frame = player_compare_frame(z_all, pool_all, picked, window)
    for bid in groups:
        frame = pd.concat(
            [frame, position_baseline(z_all, pool_all, window, baseline_pos)], ignore_index=True
        )
    frame = frame.merge(
        season_totals(pool_all, window, entities, groups), on=["player_id", "category"], how="left"
    )
    score_col = "total_score" if use_totals else "z"

    c = ui.colors()
    pcolor = dict(zip(picked, c["series4"], strict=False))
    pdash = dict(zip(picked, ["solid", "dash", "dot", "dashdot"], strict=False))
    psymbol = dict(zip(picked, ["circle", "square", "diamond", "triangle-up"], strict=False))
    for bid in groups:
        pcolor[bid], pdash[bid], psymbol[bid] = c["baseline"], "longdash", "star"

    if len(entities) == 2:
        st.markdown(f"**{head_to_head_verdict(frame, pname, by=score_col)}**")
        if use_totals:
            st.caption("Judged on season totals: games played count.")

    # --- Block 1: category radar (or, on a narrow screen, grouped bars) -------------
    st.subheader("Category profile")
    pivot_z = frame.pivot_table(index="player_id", columns="category", values="z").reindex(
        columns=COLUMNS
    )
    mobile_hint = "?1" in (st.context.headers.get("Sec-Ch-Ua-Mobile") or "")
    sticky_default("compare-chart-kind", "Bars" if mobile_hint else "Radar")
    chart_kind = st.segmented_control(
        "Chart",
        ["Radar", "Bars"],
        key="compare-chart-kind",
        label_visibility="collapsed",
        required=True,
    )
    sticky_save("compare-chart-kind", chart_kind)
    per_game_note = (
        " The chart is always per game; the table below shows season totals." if use_totals else ""
    )
    CLIP = 3.0
    if chart_kind == "Radar":
        st.caption(
            "Standard deviations above (+) or below (−) the league average, clipped "
            "to ±3 so one outlier doesn't flatten the chart (hover for the true value)."
            + per_game_note
        )
        radar = go.Figure()
        theta = [LABELS[col] for col in COLUMNS] + [LABELS[COLUMNS[0]]]
        for pid in entities:
            raw = pivot_z.loc[pid].fillna(0.0).tolist() if pid in pivot_z.index else [0.0] * 9
            clipped = [max(-CLIP, min(CLIP, v)) for v in raw]
            radar.add_trace(
                go.Scatterpolar(
                    r=clipped + clipped[:1],
                    theta=theta,
                    customdata=raw + raw[:1],
                    name=pname[pid],
                    line={"color": pcolor[pid], "width": 2, "dash": pdash[pid]},
                    marker={"size": 8, "symbol": psymbol[pid]},
                    hovertemplate="%{theta}: %{customdata:+.2f} SD<extra>"
                    + pname[pid]
                    + "</extra>",
                )
            )
        radar.add_trace(
            go.Scatterpolar(
                r=[0] * len(theta), theta=theta, mode="lines", name="League average",
                line={"color": c["muted"], "width": 1, "dash": "dot"}, hoverinfo="skip",
            )
        )  # fmt: skip
        radar.update_layout(
            polar={
                "bgcolor": "rgba(0,0,0,0)",
                "radialaxis": {
                    "range": [-CLIP, CLIP],
                    "showticklabels": False,
                    "gridcolor": c["grid"],
                },  # fmt: skip
                "angularaxis": {"gridcolor": c["grid"], "linecolor": c["grid"]},
            }
        )
        ui.show(ui.style(radar, height=440))
    else:
        st.caption("Each player's z-score per category (true value; not clipped)." + per_game_note)
        bars = go.Figure()
        for pid in entities:
            ys = pivot_z.loc[pid].tolist() if pid in pivot_z.index else [0.0] * 9
            bars.add_trace(
                go.Bar(
                    y=[LABELS[col] for col in COLUMNS],
                    x=ys,
                    orientation="h",
                    name=pname[pid],
                    marker={"color": pcolor[pid], "cornerradius": 4},
                    hovertemplate="%{y}: %{x:+.2f} SD<extra>" + pname[pid] + "</extra>",
                )
            )
        bars.update_yaxes(autorange="reversed")
        bars.update_layout(barmode="group", bargap=0.2, bargroupgap=0.08)
        ui.show(ui.style(bars, height=max(360, 56 * len(COLUMNS))))

    # --- Block 2: stat table ---------------------------------------------------------
    st.subheader("Stat table" + (" — season totals" if use_totals else " — per game"))

    def cell_text(cell: pd.Series, col: str) -> str:
        value = cell["total"] if use_totals else cell["value"]
        rank = cell["total_rank"] if use_totals else cell["rank"]
        den = cell["total_den"] if use_totals else cell["den"]
        if pd.isna(value):
            return "–"
        if col in PCT_PARTS:
            text = fmt(col, value)
            if pd.notna(den) and den > 0:
                attempts = f"{den:,.0f}" if use_totals else f"{den:.1f}"
                text += f" on {attempts} {LABELS[col].replace('%', 'A')}"
        else:
            text = f"{value:,.0f}" if use_totals else fmt(col, value)
        return text + (f" (#{int(rank)})" if pd.notna(rank) else "")

    indexed = frame.set_index(["player_id", "category"])
    stat_rows = []
    for col in COLUMNS:
        row = {"": LABELS[col]}
        scores = {}
        for pid in entities:
            if (pid, col) not in indexed.index:
                row[pname[pid]] = "–"
                continue
            cell = indexed.loc[(pid, col)]
            row[pname[pid]] = cell_text(cell, col)
            if pd.notna(cell[score_col]):
                scores[pid] = cell[score_col]
        if scores:
            best = max(scores, key=scores.get)
            if list(scores.values()).count(scores[best]) == 1:  # no bold on a tie
                row[pname[best]] = f"**{row[pname[best]]}**"
        stat_rows.append(row)

    pool_total_z = (
        z_window.pivot_table(index="player_id", columns="category", values="z", aggfunc="first")
        .reindex(columns=COLUMNS)
        .fillna(0.0)
        .sum(axis=1)
    )
    footer = {"": "Overall rank (per game)"}
    footer_z = {"": "Total z (per game)"}
    footer_gp = {"": "Games played"}
    for pid in entities:
        total_z = pivot_z.loc[pid].fillna(0.0).sum() if pid in pivot_z.index else float("nan")
        footer[pname[pid]] = (
            f"#{int((pool_total_z > total_z).sum()) + 1}" if pd.notna(total_z) else "–"
        )
        footer_z[pname[pid]] = f"{total_z:+.2f}" if pd.notna(total_z) else "–"
        gp = frame.loc[frame["player_id"] == pid, "gp"]
        footer_gp[pname[pid]] = (
            f"{gp.iloc[0]:.0f}" if not gp.empty and pd.notna(gp.iloc[0]) else "–"
        )
    table_df = pd.DataFrame([*stat_rows, footer, footer_z, footer_gp])
    st.dataframe(table_df, hide_index=True, width="stretch", height=ui.table_height(len(table_df)))
    st.caption(
        "**Bold** is the best in that category -- percentages judged with volume, like "
        "the rest of the app, so the highest percentage isn't always it. "
        + (
            "Ranks are among every pool player's season totals. Totals use games played in "
            "this window (projected games for Projected)."
            if use_totals
            else "Ranks are league-wide, the same as Player Rankings."
        )
        + (
            f" {pname[next(iter(groups))]}: the average of {len(next(iter(groups.values())))} "
            "starters; a percentage is pooled from their makes and attempts."
            if groups
            else ""
        )
    )

    # --- Block 3: fit for your team --------------------------------------------------
    st.subheader("Fit for your team")
    if mine is None:
        st.info("Sign in as a manager with a team to see this.")
    else:
        fit = analyzer.player_fit(window, mine, tuple(picked), 1.0, ())
        if groups:
            bid = next(iter(groups))
            baseline_z = pivot_z.loc[[bid], COLUMNS].fillna(0.0)
            weights = analyzer.weights_by_team(window, mine, 1.0, ())[mine]
            fit = pd.concat([fit, fit_from_weights(baseline_z, [bid], weights)])
        fit_rows = []
        for pid in entities:
            value = fit.at[pid, "value"] if pid in fit.index else None
            generic = fit.at[pid, "generic"] if pid in fit.index else None
            breakdown = fit.at[pid, "tier_breakdown"] if pid in fit.index else ""
            fit_rows.append(
                {
                    "Player": pname[pid],
                    "Value to you": f"{value:+.2f}" if pd.notna(value) else "–",
                    "General value": f"{generic:+.2f}" if pd.notna(generic) else "–",
                    "Where his value sits": breakdown or "–",
                }
            )
        st.dataframe(pd.DataFrame(fit_rows), hide_index=True, width="stretch")
        st.caption(
            f"Per game. Value to you ({names.get(mine, 'your team')}) weighs each category "
            "by your Lock/Swing/Punt tiers; general value is the same for every team."
        )

    # --- Block 4: recent form ---------------------------------------------------------
    st.subheader("Recent form")
    form_windows = [w for w in ("last_30", "last_15", "last_7", "season") if w in windows]
    if len(form_windows) < 2:
        st.caption("Not enough history yet to show a trend.")
    else:
        form = go.Figure()
        xlabels = [analyzer.STAT_WINDOWS[w] for w in form_windows]
        for pid in entities:
            ys = []
            for w in form_windows:
                if pid in groups:
                    sub = position_baseline(z_all, pool_all, w, baseline_pos)
                else:
                    sub = z_all.loc[(z_all["stat_window"] == w) & (z_all["player_id"] == pid)]
                ys.append(float(sub["z"].sum()) if not sub.empty else None)
            form.add_trace(
                go.Scatter(
                    x=xlabels,
                    y=ys,
                    mode="lines+markers",
                    name=pname[pid],
                    line={"color": pcolor[pid], "width": 2, "dash": pdash[pid]},
                    marker={"size": 9, "symbol": psymbol[pid]},
                    connectgaps=True,
                    hovertemplate="%{x}: %{y:+.2f} total z<extra>" + pname[pid] + "</extra>",
                )
            )
        form.update_yaxes(title="Total z (all 9 categories)", gridcolor=c["grid"])
        form.update_xaxes(gridcolor=c["grid"])
        ui.show(ui.style(form, height=320))
        st.caption("Each point is total z (all 9 categories) in that window -- higher is better.")

    # --- Block 5: health and durability -----------------------------------------------
    st.subheader("Health and durability")
    profile = queries.player_profile().set_index("player_id")
    health_rows = []
    for pid in entities:
        row = {"Player": pname[pid]}
        if pid in groups:
            members = [m for m in groups[pid] if m in profile.index]
            row |= {
                "Health": f"Average of {len(groups[pid])} starters",
                "Avg games (3 yrs)": profile.loc[members, "avg_games_played"].mean()
                if members
                else None,
                "Games by season": "–",
            }
        elif pid in profile.index:
            prow = profile.loc[pid]
            row["Health"] = health_text(prow)
            row["Avg games (3 yrs)"] = prow["avg_games_played"]
            row["Games by season"] = games_by_season_text(prow)
        else:
            row |= {"Health": "–", "Avg games (3 yrs)": None, "Games by season": "–"}
        health_rows.append(row)
    st.dataframe(
        pd.DataFrame(health_rows),
        column_config={
            "Avg games (3 yrs)": st.column_config.NumberColumn(
                format="%.1f", help="Average games played over the last 3 seasons he was in the NBA"
            ),
            "Games by season": st.column_config.TextColumn(
                help="Games played three, two and one seasons ago (– = not in the NBA)"
            ),
        },
        hide_index=True,
        width="stretch",
    )
    outlooks = [
        (pname[pid], profile.at[pid, "season_outlook"])
        for pid in picked
        if pid in profile.index and pd.notna(profile.at[pid, "season_outlook"])
    ]
    if outlooks:
        with st.expander("ESPN outlook for these players"):
            for name, outlook in outlooks:
                st.markdown(f"**{name}:** {outlook}")
