"""Draft page: a mock draft you can run any time, not tied to any league.

Set up the draft -- teams, rounds, your draft position, the lineup and point values,
ESPN's defaults filled in -- and draft against bots that pick like real managers, or
enter every pick yourself to follow a real draft happening elsewhere. At every pick it
suggests your five best picks: the players that leave your finished team strongest
against the finished teams around it (draft/recommend.py), with what drives each one.
Every pick updates every team's roster, so the League tab always shows where each team
stands and where it's headed.

Each person's drafts are saved to their account as they go (draft/store.py): leave and
pick up where you left off, on any device.
"""

import pandas as pd
import streamlit as st

import league
import settings
import ui
from draft import data as ddata
from draft import pool as dpool
from draft import recommend as drec
from draft import sources, store
from draft.state import Draft, DraftError, matches, normalize, parse_paste
from points.view import status_text

st.title("Draft")
st.caption(
    "A mock draft you can run any time, for any league or none. Bots that pick like real "
    "managers fill the other seats, and you see your best pick at every turn. Your draft "
    "is saved as you go: leave and pick up where you left off."
)
user = league.current_user()

# --- The draft's setup -----------------------------------------------------------------------
c1, c2, c3 = st.columns(3)
team_count = c1.number_input("Teams", min_value=4, max_value=20, value=10, key="draft-teams")
rounds = c2.number_input("Rounds", min_value=1, max_value=30, value=13, key="draft-rounds")
position = c3.number_input("Your draft position", min_value=1, max_value=int(team_count),
                           value=1, key="draft-position")  # fmt: skip
with st.expander("Lineup and point values (ESPN's defaults)"):
    e1, e2 = st.columns(2)
    slots_table = e1.data_editor(
        pd.DataFrame([*sources.ESPN_SLOTS, ("Bench", sources.ESPN_BENCH)],
                     columns=["Slot", "Players"]),
        disabled=["Slot"], hide_index=True, key="draft-slots",
        column_config={"Players": st.column_config.NumberColumn(min_value=0, max_value=10,
                                                                step=1)},
    )  # fmt: skip
    defaults = dict(sources.ESPN_POINTS)
    points_table = e2.data_editor(
        pd.DataFrame([(s, defaults.get(s, 0.0)) for s in sources.SCORABLE],
                     columns=["Stat", "Points"]),
        disabled=["Stat"], hide_index=True, key="draft-points",
    )  # fmt: skip
lineup = [(s, int(n)) for s, n in slots_table.itertuples(index=False) if s != "Bench"]
bench = int(slots_table.loc[slots_table["Slot"] == "Bench", "Players"].iloc[0])
setup = sources.make(settings.SEASON, int(team_count), int(rounds), int(position), lineup, bench,
                     list(points_table.itertuples(index=False)))  # fmt: skip
day = ddata.today()

order = setup.order
names = setup.names
league_slots = [s for s, _ in setup.slots]
me = setup.my_team

c1, c2, c3 = st.columns([1.4, 1.1, 1])
picks_by = c1.radio(
    "The other teams' picks", ["Bots make them", "I enter each one"], horizontal=True,
    key="draft-mode",
    help="Bots: a mock draft. Enter each one: follow a real draft happening elsewhere.",
)  # fmt: skip
bots = picks_by == "Bots make them"
risk = c2.selectbox(
    "Injury risk", list(dpool.RISKS), index=1, format_func=dpool.RISKS.get, key="draft-risk"
)
runs = c3.select_slider(
    "Simulations", [100, 200, 400], value=200, key="draft-runs",
    help="Simulated drafts behind each suggestion. More is steadier and slower.",
)  # fmt: skip

try:
    pool, fmt = ddata.engine(setup.key, day, risk, setup)
except ddata.FormatNotReady as error:
    st.info(str(error))
    st.stop()
frame = pool.frame
index_of = pool.index_of()
player_name = dict(zip(frame["player_id"], frame["player_name"], strict=True))


def team_label(team_id) -> str:
    return names.get(int(team_id), f"Team {team_id}")


def slots_text(text) -> str:
    """A player's eligible slots, only those this lineup uses (PG, C, UT ...)."""
    mine = set(str(text or "").split(","))
    return ", ".join(s for s in league_slots if s in mine)


# --- Your saved draft ------------------------------------------------------------------------
draft_id = store.doc_id(user["uid"], setup, "bots" if bots else "entered")
draft = store.load(league.db(), draft_id) or Draft(order)


def commit(new: Draft) -> None:
    store.save(league.db(), draft_id, new, user["uid"], league.now())


def bots_to_my_turn(d: Draft) -> Draft:
    while not d.done and d.on_clock != me:
        d.add(ddata.bot_pick(d, pool, fmt))
    return d


def add_pick(player_id: int) -> None:
    """Button / Enter callback: record a pick for the team on the clock (or the team
    chosen for a traded pick)."""
    d = Draft(draft.order, list(draft.picks))
    team = None if bots else st.session_state.get("draft-team")
    try:
        d.add(int(player_id), None if team in (None, d.on_clock) else int(team))
    except DraftError as error:
        st.session_state["draft-problem"] = str(error)
        return
    if bots and st.session_state.get("draft-auto", True):
        d = bots_to_my_turn(d)
    commit(d)
    st.session_state["draft-entry"] = ""
    st.session_state["draft-choices"] = []
    st.session_state["draft-team"] = None


available = {int(pid): name for pid, name in player_name.items() if int(pid) not in draft.taken()}


def enter_typed() -> None:
    typed = st.session_state.get("draft-entry", "")
    found = matches(typed, available)
    clear = found and (len(found) == 1 or normalize(available[found[0]]) == normalize(typed))
    if clear:
        add_pick(found[0])
    else:
        st.session_state["draft-choices"] = found
        if not found:
            st.session_state["draft-problem"] = f"No available player matches “{typed}”."


def undo() -> None:
    d = Draft(draft.order, list(draft.picks))
    if bots:  # take back the bots' picks too, back to your last pick
        while d.picks and d.picks[-1][0] != me:
            d.undo()
    d.undo()
    commit(d)


def start_over() -> None:
    store.clear(league.db(), draft_id)


# --- Top strip and pick entry ----------------------------------------------------------------
if bots and st.session_state.get("draft-auto", True) and not draft.done and draft.on_clock != me:
    draft = bots_to_my_turn(Draft(draft.order, list(draft.picks)))
    commit(draft)
    available = {pid: name for pid, name in available.items() if pid not in draft.taken()}

if draft.done:
    st.success("The draft is over. The League tab projects where every team finishes.")
    st.button("Start a new draft", type="primary", on_click=start_over, key="draft-new")
else:
    rnd, in_round = order.round_of(draft.next_pick)
    upcoming = draft.next_pick_of(me)
    where = f"Round {rnd}, pick {in_round} (#{draft.next_pick})"
    if draft.on_clock == me:
        st.markdown(f"### You're on the clock · {where}")
    else:
        wait = f"You pick in {upcoming - draft.next_pick} (#{upcoming})" if upcoming else (
            "You have no picks left"
        )  # fmt: skip
        st.markdown(f"### {where}: {team_label(draft.on_clock)} · {wait}")

    if not bots or draft.on_clock == me:
        st.text_input(
            "Enter a pick", key="draft-entry", on_change=enter_typed,
            placeholder="A few letters of his name, then Enter", label_visibility="collapsed",
        )  # fmt: skip
        choices = [p for p in st.session_state.get("draft-choices", []) if p in available]
        if choices:
            cols = st.columns(len(choices))
            for col, pid in zip(cols, choices, strict=True):
                col.button(available[pid], key=f"draft-choice-{pid}", on_click=add_pick,
                           args=(pid,))  # fmt: skip
    problem = st.session_state.pop("draft-problem", None)
    if problem:
        st.error(problem)

b1, b2, b3, b4 = st.columns(4)
b1.button("Undo", icon=":material/undo:", on_click=undo, disabled=not draft.picks, key="draft-undo")
if not bots:
    b3.toggle("Follow along", key="draft-follow",
              help="Re-read the draft every 3 seconds, for a second screen.")  # fmt: skip
else:

    def run_bots() -> None:
        commit(bots_to_my_turn(Draft(draft.order, list(draft.picks))))

    b2.button("Bots pick to my turn", icon=":material/fast_forward:", disabled=draft.done,
              on_click=run_bots, key="draft-bots")  # fmt: skip
    b3.toggle("Bots pick right away", value=True, key="draft-auto")
with b4.popover("Start over", icon=":material/restart_alt:", disabled=not draft.picks):
    st.write("Clear every pick of this draft?")
    st.button("Clear the draft", type="primary", on_click=start_over, key="draft-clear")

if not bots and not draft.done:
    with st.expander("Picking for another team, or pasting picks to catch up"):
        st.selectbox(
            "Who's picking", [None, *order.teams],
            format_func=lambda t: "The team on the clock" if t is None else team_label(t),
            key="draft-team", help="For a traded pick.",
        )  # fmt: skip
        pasted = st.text_area(
            "Paste picks", placeholder="Copy the pick list from ESPN's draft room"
        )
        if st.button("Add these picks", key="draft-paste") and pasted:
            d = Draft(draft.order, list(draft.picks))
            added = 0
            for pid in parse_paste(pasted, available):
                if not d.done:
                    d.add(pid)
                    added += 1
            commit(d)
            st.toast(f"Added {added} picks.")
            st.rerun()

if not bots and st.session_state.get("draft-follow"):

    @st.fragment(run_every=3)
    def follow(seen: tuple) -> None:
        latest = store.load(league.db(), draft_id)
        if latest is not None and tuple(latest.picks) != seen:
            st.rerun()

    follow(tuple(draft.picks))

# --- Your best picks ----------------------------------------------------------------------------
adv = ddata.advice(setup.key, day, risk, order.teams, order.rounds, order.snake,
                   tuple(draft.picks), me, runs, setup)  # fmt: skip
my_roster = [index_of.get(p, -1) for p in draft.rosters().get(me, [])]


def ordinal(n: float) -> str:
    n = int(round(n))
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


if adv.pick is not None and not adv.picks.empty:
    st.subheader("Your best picks" + ("" if adv.on_clock else f" for pick #{adv.pick}"))
    st.caption(
        f"Ranked by your {fmt.wins_label.lower()} once every roster is full: each suggestion "
        f"plays out the rest of the draft {runs} times, with the other managers drafting "
        "like real ones (ESPN's board, their own tastes, their rosters' needs) and you "
        "drafting by these projections."
    )
    noise = float(adv.picks["se"].iloc[1]) if len(adv.picks) > 1 else 0.0
    for n, row in enumerate(adv.picks.itertuples()):
        p = frame.iloc[row.index]
        with st.container(border=True):
            head, button = st.columns([5, 1])
            head.markdown(
                f"**{n + 1}. {p['player_name']}** · {p['pro_team'] or 'FA'} · "
                f"{slots_text(p['eligible_slots'])}"
                + (f" · :red[{status_text(p)}]" if status_text(p) else "")
            )
            if draft.on_clock == me:
                button.button("Draft", key=f"draft-card-{row.player_id}", type="primary",
                              on_click=add_pick, args=(row.player_id,))  # fmt: skip
            versus = "vs the next best" if n == 0 else "vs the top pick"
            if n == 0 and abs(row.edge) < 2 * noise:
                versus += ", within the simulations' noise"
            st.markdown(
                f"{fmt.wins_label}: **{row.wins:.2f}** ({row.edge:+.2f} {versus}) · your "
                f"projected rank **{ordinal(row.rank)}** of {len(order.teams)}"
            )
            reasons = [f"{p['fpg']:.1f} FP/G · {p['games']:.0f} games · "
                       f"{row.value:+,.0f} season points above replacement"]  # fmt: skip
            if adv.on_clock:
                reasons.append(f"{row.lasts:.0%} chance he lasts to your next pick")
            else:
                reasons.append(f"{row.there:.0%} chance he's there at your pick")
            filled = drec.fills(pool, my_roster, row.index)
            if filled:
                reasons.append("Fills your empty " + ", ".join(filled))
            if row.taken_by:
                team, share = row.taken_by
                if team != me:
                    reasons.append(f"If you pass, most likely to {team_label(team)} ({share:.0%})")
            if row.next:
                reasons.append(
                    "Likely next for you: "
                    + ", ".join(f"{frame.iloc[i]['player_name']} ({s:.0%})" for i, s in row.next)
                )
            st.caption(" · ".join(reasons))

# --- Board, Available, League, My team ---------------------------------------------------------
board_tab, available_tab, league_tab, mine_tab = st.tabs(
    ["Board", "Available", "League", "My team"]
)

with board_tab:
    grid = {team_label(t) + (" (you)" if t == me else ""): [""] * order.rounds for t in order.teams}
    for k, (team, pid) in enumerate(draft.picks, start=1):
        rnd, _ = order.round_of(k)
        column = team_label(team) + (" (you)" if team == me else "")
        grid.setdefault(column, [""] * order.rounds)
        grid[column][rnd - 1] = player_name.get(pid, f"#{pid}")
    st.dataframe(pd.DataFrame(grid, index=[f"Round {r}" for r in range(1, order.rounds + 1)]),
                 width="stretch", height=ui.table_height(order.rounds))  # fmt: skip

with available_tab:
    left = frame.loc[[int(pid) not in draft.taken() for pid in frame["player_id"]]].copy()
    there = adv.base.available_at.get(adv.pick)
    left["there"] = there.mean(axis=0)[left.index] if there is not None else float("nan")
    f1, f2 = st.columns([2, 1])
    search = f1.text_input("Search", key="draft-search", placeholder="Player name")
    slot = f2.multiselect("Can start at", [s for s in league_slots if s != "UT"],
                          key="draft-slot", placeholder="Any slot")  # fmt: skip
    if search:
        left = left.loc[left["player_name"].str.contains(search, case=False, regex=False)]
    if slot:
        left = left.loc[left["slots"].map(lambda s: bool(s & set(slot)))]
    left = left.sort_values("value", ascending=False)
    st.dataframe(
        pd.DataFrame(
            {
                "Player": left["player_name"],
                "NBA": left["pro_team"],
                "Slots": left["eligible_slots"].map(slots_text),
                "Status": [status_text(r) for _, r in left.iterrows()],
                "FP/G": left["fpg"],
                "Games": left["games"],
                "Value": left["value"],
                "ADP": left["adp"],
                "ESPN rank": left["rank"],
                "There at your pick": left["there"],
            }
        ),
        column_config={
            "FP/G": st.column_config.NumberColumn(format="%.1f"),
            "Games": st.column_config.NumberColumn(format="%.0f"),
            "Value": st.column_config.NumberColumn(
                format="%+,.0f", help="Season points above replacement."
            ),
            "ADP": st.column_config.NumberColumn(format="%.1f"),
            "There at your pick": st.column_config.ProgressColumn(
                format="percent", min_value=0, max_value=1
            ),
        },
        hide_index=True,
        width="stretch",
        height=500,
    )
    if not draft.done and (not bots or draft.on_clock == me):
        a1, a2 = st.columns([3, 1])
        chosen = a1.selectbox(
            "Draft a player from the list", list(left["player_id"]), index=None,
            format_func=lambda p: player_name[p], key="draft-pick-any",
        )  # fmt: skip
        a2.button("Draft him", disabled=chosen is None, on_click=add_pick, args=(chosen,),
                  key="draft-pick-any-go")  # fmt: skip

with league_tab:
    table = adv.league.copy()
    table["Team"] = [team_label(t) + (" (you)" if t == me else "") for t in table["team_id"]]
    st.caption(
        f"Each team's roster now and, from the simulations, its finished roster: "
        f"{fmt.strength_label.lower()}, {fmt.wins_label.lower()} and its rank, all by these "
        "projections. A team that has picked less isn't ranked last for it: its later picks "
        "are played out too. Your later picks follow these projections and the others' "
        "follow ESPN's board, which favors you; real seasons also stray from projections."
    )
    st.dataframe(
        table[["Team", "players", "strength_now", "strength", "wins", "rank", "first"]],
        column_config={
            "players": st.column_config.NumberColumn("Players", format="%d"),
            "strength_now": st.column_config.NumberColumn(
                "Now", format="%,.0f", help=f"{fmt.strength_label}, players so far."
            ),  # fmt: skip
            "strength": st.column_config.NumberColumn(
                "Finished", format="%,.0f", help=f"{fmt.strength_label}, projected."
            ),  # fmt: skip
            "wins": st.column_config.NumberColumn(fmt.wins_label, format="%.2f"),
            "rank": st.column_config.NumberColumn("Projected rank", format="%.1f"),
            "first": st.column_config.ProgressColumn(
                "Strongest roster",
                format="percent",
                min_value=0,
                max_value=1,
                help="Share of the simulated drafts where this roster projects strongest.",
            ),  # fmt: skip
        },
        hide_index=True,
        width="stretch",
        height=ui.table_height(len(table)),
    )
    team = st.selectbox("Roster", list(order.teams), index=list(order.teams).index(me),
                        format_func=team_label, key="draft-roster-team")  # fmt: skip
    roster = draft.rosters().get(team, [])
    if not roster:
        st.caption("No picks yet.")
    else:
        rows = frame.set_index("player_id").reindex(roster)
        st.dataframe(
            pd.DataFrame(
                {
                    "Pick": [k for k, (t, _) in enumerate(draft.picks, 1) if t == team],
                    "Player": [player_name.get(p, f"#{p}") for p in roster],
                    "Slots": rows["eligible_slots"].map(slots_text).values,
                    "FP/G": rows["fpg"].values,
                    "Games": rows["games"].values,
                }
            ),
            column_config={
                "FP/G": st.column_config.NumberColumn(format="%.1f"),
                "Games": st.column_config.NumberColumn(format="%.0f"),
            },  # fmt: skip
            hide_index=True,
            width="stretch",
        )

with mine_tab:
    mine_row = adv.league.loc[adv.league["team_id"] == me].iloc[0]
    leader = adv.league.iloc[0]
    average = adv.league["strength"].mean()
    m1, m2, m3 = st.columns(3)
    m1.metric(f"{fmt.strength_label} (finished)", f"{mine_row['strength']:,.0f}",
              f"{mine_row['strength'] - average:+,.0f} vs the league average")  # fmt: skip
    m2.metric(fmt.wins_label, f"{mine_row['wins']:.2f}",
              help=f"Out of {fmt.max_wins(len(order.teams)):g}.")  # fmt: skip
    m3.metric(
        "Projected rank", ordinal(mine_row["rank"]),
        f"strongest in {mine_row['first']:.0%} of simulations", delta_color="off",
    )  # fmt: skip
    if leader["team_id"] != me:
        st.caption(
            f"Projected leader: {team_label(leader['team_id'])}, "
            f"{leader['strength'] - mine_row['strength']:+,.0f} ahead of you."
        )
    empty = [s for s in pool.slot_types if s not in {x for i in my_roster if i >= 0
                                                     for x in frame.iloc[i]["slots"]}]  # fmt: skip
    if empty:
        st.caption("Starting slots you haven't filled: " + ", ".join(empty))
