"""Compare page (Step 6): pick two teams + week or season; radar chart of category
z-scores and side-by-side bars per category. Reads v_team_week_cats; the z-scores
are computed in compare.py because the period is chosen on this page.
"""

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import login
import queries
import ui
from categories import CATEGORIES, COLUMNS, LABELS, fmt
from compare import head_to_head, period_lines, zscores

st.title("Compare")

weeks = queries.team_week_cats()
names = queries.teams().set_index("team_id")["team_name"]
if weeks.empty:
    st.info("No matchup data yet.")
    st.stop()

team_ids = sorted(weeks["team_id"].unique(), key=lambda t: names.get(t, ""))
week_options = ["Season", *sorted(weeks["matchup_period"].unique(), reverse=True)]

c1, c2, c3 = st.columns([2, 2, 1])
mine = login.my_team()
a = c1.selectbox(
    "Team", team_ids, index=team_ids.index(mine) if mine in team_ids else 0, format_func=names.get
)
b = c2.selectbox("Against", [t for t in team_ids if t != a], index=0, format_func=names.get)
period = c3.selectbox(
    "Period", week_options, format_func=lambda w: w if w == "Season" else f"Week {w}"
)

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
            "radialaxis": {"range": [-span, span], "showticklabels": False, "gridcolor": c["grid"]},
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
