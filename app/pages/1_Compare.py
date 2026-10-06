"""Compare page: pick two teams + week or season; radar chart of category z-scores
and side-by-side bars per category. Reads m_team_week_cats; the z-scores are
computed in compare.py because the period is chosen on this page. Lower-is-better
categories (turnovers) are flipped in the z-scores and the head-to-head, so outward
on the radar is always better.
"""

import math

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import league
import queries
import ui
from categories import fmt, keys
from compare import head_to_head, period_lines, scores, zscores

st.title("Compare")
ctx = league.current()
cats = ctx.cats
COLUMNS = keys(cats)

weeks = queries.team_week_cats(ctx.league_id, ctx.version)
names = ctx.team_names
if weeks.empty:
    st.info("No matchup data yet.")
    st.stop()

team_ids = sorted((int(t) for t in weeks["team_id"].unique()), key=lambda t: names.get(t, ""))
week_options = ["Season", *sorted(weeks["matchup_period"].unique(), reverse=True)]

c1, c2, c3 = st.columns([2, 2, 1])
mine = ctx.my_team
a = c1.selectbox(
    "Team", team_ids, index=team_ids.index(mine) if mine in team_ids else 0, format_func=names.get
)
b = c2.selectbox("Against", [t for t in team_ids if t != a], index=0, format_func=names.get)
period = c3.selectbox(
    "Period", week_options, format_func=lambda w: w if w == "Season" else f"Week {w}"
)

lines = period_lines(weeks, cats, None if period == "Season" else int(period))
z = zscores(lines, cats)
score_lines = scores(lines, cats)
wins, losses, ties = head_to_head(score_lines.loc[a], score_lines.loc[b])
verdict = "beat" if wins > losses else "lose to" if wins < losses else "tie"
when = "on season averages" if period == "Season" else f"in week {period}"
st.markdown(
    f"**{names[a]}** would {verdict} **{names[b]}** {when}, "
    f"winning {wins}, losing {losses} and tying {ties} of the {len(cats)} categories."
)

c = ui.colors()
pair = [(a, c["series"][0]), (b, c["series"][1])]

if z.loc[[a, b]].isna().all().all():
    st.info("Every team is level in every category so far, so there's nothing to chart yet.")
else:
    st.subheader("Category profile")
    st.caption(
        "Standard deviations better (+) or worse (−) than the league average. "
        "Lower-is-better categories are flipped, so outward is always better."
    )
    radar = go.Figure()
    theta = [*COLUMNS, COLUMNS[0]]
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
            "radialaxis": {"range": [-span, span], "showticklabels": False, "gridcolor": c["grid"]},
            "angularaxis": {"gridcolor": c["grid"], "linecolor": c["grid"]},
        }
    )
    ui.show(ui.style(radar, height=420))

st.subheader("By category")
n_cols = 3
n_rows = math.ceil(len(cats) / n_cols)
bars = make_subplots(
    rows=n_rows,
    cols=n_cols,
    subplot_titles=[c.label + (" (lower wins)" if c.lower_is_better else "") for c in cats],
)
for i, cat in enumerate(cats):
    for team, color in pair:
        value = lines.loc[team, cat.key]
        bars.add_trace(
            go.Bar(
                x=[names[team]],
                y=[value],
                marker={"color": color, "cornerradius": 4},
                name=names[team],
                showlegend=i == 0,
                text=[fmt(cat, value)],
                textposition="outside",
                cliponaxis=False,
                hovertemplate=f"{cat.label}: %{{text}}<extra>{names[team]}</extra>",
            ),
            row=i // n_cols + 1,
            col=i % n_cols + 1,
        )
bars.update_xaxes(showticklabels=False)
bars.update_yaxes(showticklabels=False, showgrid=False, rangemode="tozero")
bars.update_layout(bargap=0.15)
ui.style(bars, height=180 * n_rows + 20).update_layout(margin={"t": 72}, legend={"y": 1.1})
ui.show(bars)

with st.expander("Table view"):
    st.dataframe(
        {
            "Category": COLUMNS,
            names[a]: [fmt(c, lines.at[a, c.key]) for c in cats],
            names[b]: [fmt(c, lines.at[b, c.key]) for c in cats],
        },
        hide_index=True,
        width="stretch",
    )
