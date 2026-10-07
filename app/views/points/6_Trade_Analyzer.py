"""Trade Analyzer for a points league: waiver pickups and trades for one team, ranked
by how much each raises its expected wins a week (the chance of outscoring each
other team in a week, added up), plus a mock-trade simulator.

Controls: team (your own; a commissioner can pick any) and stat window. Five tabs:
Team profile, Waiver wire, Trade finder, Create a trade (Offer Builder and Search by
player) and Mock trade. Searches rank every deal with the fast estimate and show the
best ones rescored with the full daily lineup simulation -- the same numbers Mock
trade shows for a loaded deal. The math lives in app/points (tested).
"""

import pandas as pd
import streamlit as st

import ui
from points import data, explain, model, view
from points.trades import (
    CLOSE_CALL,
    COSTS_YOU,
    LIKELY,
    MAX_GAIN,
    THEY_SAY_NO,
    WIN_WIN,
)

ctx = view.header("Trade Analyzer")
c1, c2 = st.columns([1.6, 1])
me = view.my_team_picker(ctx, c1)
window = view.window_picker(ctx, c2, key="trade-window")
key = data.search_key(ctx, window)
setup = data.setup(*key)
players = setup.players
name = players["player_name"]
if me not in setup.teams:
    st.info("This team has no players with stats yet.")
    st.stop()
mu = setup.team_mu(full=True)
e = model.expected_wins(mu, setup.sigma)
max_e = len(mu) - 1
team_ids = list(setup.teams)
FREE_AGENTS = 0


def team_label(team_id) -> str:
    return "Free agents" if team_id == FREE_AGENTS else view.team_label(ctx, team_id)


def names_of(ids) -> str:
    return explain.names(players, ids)


def keep_valid(state_key: str, options: list, multi: bool) -> None:
    """Drop a stored selection that no longer fits the options (e.g. after the
    partner changed), before the widget renders."""
    value = st.session_state.get(state_key)
    if value is None:
        return
    if multi:
        value = value if isinstance(value, list) else [value]
        st.session_state[state_key] = [v for v in value if v in options]
    elif value not in options:
        st.session_state[state_key] = None


def load_into_mock(partner, give=(), get=(), my_add=(), my_drop=(), their_add=(),
                   their_drop=()) -> None:  # fmt: skip
    """Button callback: fill the Mock trade tab's controls with one move."""
    st.session_state["pmock-partner"] = int(partner)
    for state_key, ids in (("pmock-give", give), ("pmock-get", get), ("pmock-my-add", my_add),
                           ("pmock-my-drop", my_drop), ("pmock-their-add", their_add),
                           ("pmock-their-drop", their_drop)):  # fmt: skip
        st.session_state[state_key] = [int(x) for x in ids]
    st.toast("Loaded. Open the Mock trade tab to see it.")


def compare_players(ids) -> None:
    st.session_state["compare-mode"] = "Players"
    st.session_state["compare-players"] = [int(x) for x in ids][:4]
    st.session_state["compare-jump"] = True


if st.session_state.pop("compare-jump", False):
    st.switch_page("views/points/1_Compare.py")


def deals_table(deals: pd.DataFrame, with_status: bool = False) -> pd.DataFrame:
    labels = {LIKELY: "Likely to work", COSTS_YOU: "Costs you", THEY_SAY_NO: "They'd likely say no"}
    out = pd.DataFrame(
        {
            "Partner": [team_label(t) for t in deals["partner_id"]],
            "You give": [names_of(g) for g in deals["give_ids"]],
            "You get": [names_of(g) for g in deals["get_ids"]],
            "Your wins a week": deals["dE_me"],
            "Their wins a week": deals["dE_them"],
            "Your points a week": deals["dmu_me"],
            "Their points a week": deals["dmu_them"],
            "Flag": ["Lopsided" if x else "" for x in deals["lopsided"]],
        }
    )
    if with_status:
        out.insert(0, "Status", deals["status"].map(labels))
    return out


DEAL_COLUMNS = {
    "Your wins a week": st.column_config.NumberColumn(format="%+.2f"),
    "Their wins a week": st.column_config.NumberColumn(format="%+.2f"),
    "Your points a week": st.column_config.NumberColumn(format="%+.1f"),
    "Their points a week": st.column_config.NumberColumn(format="%+.1f"),
}


def deal_details(deals: pd.DataFrame, prefix: str) -> None:
    """Pick one deal: why it helps, the pitch, and the buttons."""
    if deals.empty:
        return
    pick = st.selectbox(
        "See a deal",
        list(range(len(deals))),
        format_func=lambda i: (
            f"{team_label(deals.iloc[i]['partner_id'])}: {names_of(deals.iloc[i]['give_ids'])} "
            f"for {names_of(deals.iloc[i]['get_ids'])}"
        ),
        key=f"{prefix}-pick",
    )
    deal = deals.iloc[pick]
    with st.container(border=True):
        st.markdown("**Why it helps you**")
        st.write(explain.why(players, deal))
        their = explain.roster_moves(players, deal["their_add_ids"], deal["their_drop_ids"],
                                     you=False)  # fmt: skip
        if their:
            st.caption(their)
        st.markdown("**The pitch**")
        st.code(explain.pitch(players, deal), language=None, wrap_lines=True)
        b1, b2 = st.columns(2)
        b1.button(
            "Load into mock trade", key=f"{prefix}-load", on_click=load_into_mock,
            args=(deal["partner_id"], deal["give_ids"], deal["get_ids"], deal["my_add_ids"],
                  deal["my_drop_ids"], deal["their_add_ids"], deal["their_drop_ids"]),
        )  # fmt: skip
        b2.button(
            "Compare players", key=f"{prefix}-compare", on_click=compare_players,
            args=([*deal["give_ids"], *deal["get_ids"]],),
        )  # fmt: skip


profile_tab, waiver_tab, finder_tab, create_tab, mock_tab = st.tabs(
    ["Team profile", "Waiver wire", "Trade finder", "Create a trade", "Mock trade"]
)

# --- Team profile ----------------------------------------------------------------------------
with profile_tab:
    roster = setup.roster(me)
    sim = setup.full_weeks(roster)
    rank = int(mu.rank(ascending=False, method="min")[me])
    m1, m2, m3 = st.columns(3)
    m1.metric("Projected points a week", f"{mu[me]:,.1f}", help="Rest of the regular season.")
    m1.caption(f"{rank} of {len(mu)} in the league")
    m2.metric("Expected wins a week", f"{e[me]:.2f}", help=f"All-play, out of {max_e}.")
    m2.caption(f"League average {max_e / 2:.1f}")
    m3.metric(
        f"Week {ctx.current_week} projection", f"{sim['weeks'].get(ctx.current_week, 0):,.1f}"
    )
    st.caption(
        f"Weekly scores spread about {setup.sigma:,.0f} points around a team's projection "
        f"({setup.spread_note}). A point is worth the same to every team, so trades help "
        "both sides through lineups: open roster spots, games, positions and injuries."
    )
    weeks = len(setup.weeks)
    starts = pd.Series(sim["starts"], dtype="float64").reindex(roster).fillna(0) / weeks
    st.subheader("Your lineup")
    st.dataframe(
        pd.DataFrame(
            {
                "Player": name.loc[roster],
                "Slots": players.loc[roster, "eligible_slots"].map(
                    lambda s: view.slots_text(ctx, s)
                ),
                "Status": [view.status_text(r) for _, r in players.loc[roster].iterrows()],
                "FP/G": players.loc[roster, "fpg"],
                "PAR": players.loc[roster, "par"],
                "Games a week": players.loc[roster, "games"],
                "Starts a week": starts,
                "Points a week": starts * players.loc[roster, "fpg"],
            }
        ).sort_values("Points a week", ascending=False),
        column_config={
            c: st.column_config.NumberColumn(format="%.1f")
            for c in ("FP/G", "Games a week", "Starts a week", "Points a week")
        }
        | {"PAR": st.column_config.NumberColumn(format="%+.1f")},
        hide_index=True,
        width="stretch",
        height=ui.table_height(len(roster)),
    )
    bench = [p for p in roster if starts[p] < 0.5 * players.at[p, "games"]]
    if bench:
        st.caption(
            "Sitting more than half his games: " + names_of(bench) + ". A 2-for-1 that "
            "turns depth like this into one better player can help you."
        )

# --- Waiver wire -----------------------------------------------------------------------------
with waiver_tab:
    moves = data.waiver_moves(key, me)
    if moves.empty:
        st.info("No free agent raises your expected wins right now.")
    else:
        st.caption(
            "Add a free agent (dropping one of your players unless you have an open spot), "
            "ranked by the change in your expected wins a week."
        )
        table = pd.DataFrame(
            {
                "Add": [explain.player_text(players, a) for a in moves["add_id"]],
                "Drop": [
                    "Nobody (open spot)" if pd.isna(d) else name[int(d)] for d in moves["drop_id"]
                ],
                "Wins a week": moves["dE"],
                "Points a week": moves["dmu"],
            }
        )
        st.dataframe(
            table,
            column_config={
                "Wins a week": st.column_config.NumberColumn(format="%+.2f"),
                "Points a week": st.column_config.NumberColumn(format="%+.1f"),
            },
            hide_index=True,
            width="stretch",
            height=ui.table_height(len(table)),
        )
        pick = st.selectbox("Load a move", list(range(len(moves))),
                            format_func=lambda i: f"Add {name[int(moves.iloc[i]['add_id'])]}",
                            key="waiver-pick")  # fmt: skip
        move = moves.iloc[pick]
        drop = [] if pd.isna(move["drop_id"]) else [int(move["drop_id"])]
        w1, w2 = st.columns(2)
        w1.button("Load into mock trade", key="waiver-load", on_click=load_into_mock,
                  args=(FREE_AGENTS, drop, [int(move["add_id"])]))  # fmt: skip
        w2.button("Compare players", key="waiver-compare", on_click=compare_players,
                  args=([int(move["add_id"]), *drop],))  # fmt: skip

# --- Trade finder ----------------------------------------------------------------------------
with finder_tab:
    deals = data.find_trades(key, me)
    st.caption(
        "Every 1-for-1, 2-for-1, 1-for-2 and 2-for-2 deal with every team that raises both "
        "teams' expected wins a week and doesn't look lopsided."
    )
    if deals.empty:
        st.info(
            "No win-win trade right now. Try Create a trade for deals that cost a partner a little."
        )
    else:
        st.dataframe(deals_table(deals), column_config=DEAL_COLUMNS, hide_index=True,
                     width="stretch", height=ui.table_height(len(deals)))  # fmt: skip
        deal_details(deals, "finder")

# --- Create a trade --------------------------------------------------------------------------
ACCEPTANCE = {"Win-win": WIN_WIN, "Close call": CLOSE_CALL, "Max gain": MAX_GAIN}
with create_tab:
    st.subheader("Offer Builder")
    st.caption(
        "Pick the players you're willing to move and (optionally) who with. Every deal "
        "built from them that raises your expected wins a week comes back."
    )
    mine = setup.roster(me)
    keep_valid("pob-block", mine, multi=True)
    block = st.multiselect(
        "Trade block", mine, format_func=lambda p: explain.player_text(players, p),
        max_selections=6, key="pob-block",
    )  # fmt: skip
    o1, o2, o3 = st.columns(3)
    target = o1.selectbox("Target team", [None, *[t for t in team_ids if t != me]],
                          format_func=lambda t: "Any team" if t is None else team_label(t),
                          key="pob-target")  # fmt: skip
    max_give = o2.selectbox("Max players you give", [1, 2, 3], index=1, key="pob-give")
    max_get = o3.selectbox("Max players you get", [1, 2, 3], index=1, key="pob-get")
    acceptance = st.radio(
        "Acceptance level", list(ACCEPTANCE), horizontal=True, key="pob-accept",
        help="Win-win: they don't lose expected wins and it isn't lopsided. Close call: it "
        "costs them up to 0.2 wins a week but looks fair. Max gain: no limit, lopsided deals "
        "flagged.",
    )  # fmt: skip
    with st.expander("Advanced"):
        exclude = st.checkbox("Skip injured players you'd receive", value=True, key="pob-injured")
        uneven = st.checkbox("Allow uneven deals (like 2-for-1)", value=True, key="pob-uneven")
    if st.button("Find offers", type="primary", key="pob-find"):
        if not block:
            st.error("Pick at least one player you'd trade.")
        else:
            st.session_state["pob-params"] = (
                tuple(sorted(int(b) for b in block)),
                tuple([int(target)] if target else [t for t in team_ids if t != me]),
                max_give, max_get, ACCEPTANCE[acceptance], exclude, uneven,
            )  # fmt: skip
    params = st.session_state.get("pob-params")
    if params:
        offers, problem = data.build_offers(key, me, *params)
        if problem:
            st.error(problem)
        elif offers is None or offers.empty:
            st.info("No offer passes at this acceptance level. Try Close call or Max gain.")
        else:
            st.caption(f"{len(offers)} offers found.")
            st.dataframe(deals_table(offers), column_config=DEAL_COLUMNS, hide_index=True,
                         width="stretch", height=ui.table_height(len(offers)))  # fmt: skip
            deal_details(offers, "pob")

    st.divider()
    st.subheader("Search by player")
    on_rosters = (
        players["team_id"].notna() & (players["team_id"] != me) & ~players["is_ir"].astype(bool)
    )
    others = players.loc[on_rosters].sort_values("fpg", ascending=False)
    s1, s2 = st.columns([2, 1])
    wanted = s1.selectbox(
        "Player you want", [int(p) for p in others.index], index=None,
        format_func=lambda p: f"{name[p]} ({team_label(players.at[p, 'team_id'])}, "
        f"{players.at[p, 'fpg']:.1f} FP/G)",
        placeholder="Type a player's name...", key="ptarget",
    )  # fmt: skip
    size = s2.radio("Deal size", [1, 2], index=1, horizontal=True, key="ptarget-size",
                    help="At most this many players each way.")  # fmt: skip
    if wanted is None:
        st.info("Pick a player to see trades for him.")
    else:
        found = data.deals_for_target(key, me, int(wanted), int(size))
        if found.empty:
            st.info("No deal for him to show.")
        else:
            st.caption(
                "Likely to work: you gain, they don't lose and it looks fair. Costs you: "
                "they'd accept, but it costs you (his realistic price). They'd likely say no: "
                "it helps you but costs them or looks lopsided."
            )
            st.dataframe(deals_table(found, with_status=True), column_config=DEAL_COLUMNS,
                         hide_index=True, width="stretch",
                         height=ui.table_height(len(found)))  # fmt: skip
            deal_details(found, "ptarget")

# --- Mock trade -----------------------------------------------------------------------------
with mock_tab:
    partners = [FREE_AGENTS, *[t for t in team_ids if t != me]]
    keep_valid("pmock-partner", partners, multi=False)
    partner = st.selectbox("Partner", partners, format_func=team_label, key="pmock-partner")
    waiver = partner == FREE_AGENTS
    fas = setup.free_agents()
    their_side = fas if waiver else setup.roster(partner)
    mine = setup.roster(me)
    for state_key, options in (("pmock-give", mine), ("pmock-get", their_side),
                               ("pmock-my-add", fas), ("pmock-my-drop", mine)):  # fmt: skip
        keep_valid(state_key, options, multi=True)

    def label(p) -> str:
        return explain.player_text(players, p)

    k1, k2 = st.columns(2)
    give = k1.multiselect("You drop" if waiver else "You send", mine, format_func=label,
                          key="pmock-give")  # fmt: skip
    get = k2.multiselect("You add" if waiver else "You get", their_side, format_func=label,
                         key="pmock-get")  # fmt: skip
    st.markdown("**Your other moves**")
    k3, k4 = st.columns(2)
    my_add = k3.multiselect("Add free agents", [p for p in fas if p not in get],
                            format_func=label, key="pmock-my-add")  # fmt: skip
    my_drop = k4.multiselect("Drop players", [p for p in mine if p not in give],
                             format_func=label, key="pmock-my-drop")  # fmt: skip
    their_add, their_drop = [], []
    if not waiver:
        theirs = setup.roster(partner)
        keep_valid("pmock-their-add", fas, multi=True)
        keep_valid("pmock-their-drop", theirs, multi=True)
        with st.expander(f"{team_label(partner)}'s other moves"):
            their_add = st.multiselect(
                "They add", [p for p in fas if p not in (*get, *my_add)], format_func=label,
                key="pmock-their-add",
            )  # fmt: skip
            their_drop = st.multiselect(
                "They drop", [p for p in theirs if p not in get], format_func=label,
                key="pmock-their-drop",
            )  # fmt: skip
    size_now = len(mine)
    size_after = size_now - len(give) + len(get) + len(my_add) - len(my_drop)
    if size_after == size_now:
        st.caption(f"Your roster: {size_now} players before and after. ✓")
    else:
        fix = (f"drop {size_after - size_now} more" if size_after > size_now
               else f"add {size_now - size_after} more")  # fmt: skip
        st.caption(f"Your roster: {size_now} → {size_after} players. To stay at {size_now}, {fix}.")
    if not (give or get or my_add or my_drop):
        st.info("Pick players to see the result.")
        st.stop()

    moves = (tuple(give), tuple(get), tuple(my_add), tuple(my_drop), tuple(their_add),
             tuple(their_drop))  # fmt: skip
    out = data.mock_trade(key, me, None if waiver else partner, *moves)
    sides = [me] if waiver else [me, partner]
    columns = st.columns(len(sides))
    for col, team in zip(columns, sides, strict=True):
        with col:
            st.markdown(f"**{team_label(team)}**")
            a, b = st.columns(2)
            a.metric("Points a week", f"{out['mu_after'][team]:,.1f}",
                     f"{out['mu_after'][team] - out['mu_before'][team]:+.1f}")  # fmt: skip
            b.metric("Expected wins a week", f"{out['e_after'][team]:.2f}",
                     f"{out['dE'][team]:+.2f}")  # fmt: skip
    st.subheader("Your lineup after")
    after = out["rosters"][me]
    sim = setup.full_weeks(after)
    starts = pd.Series(sim["starts"], dtype="float64").reindex(after).fillna(0) / len(setup.weeks)
    st.dataframe(
        pd.DataFrame(
            {
                "Player": name.loc[after],
                "New": ["●" if p in (*get, *my_add) else "" for p in after],
                "FP/G": players.loc[after, "fpg"],
                "Games a week": players.loc[after, "games"],
                "Starts a week": starts,
                "Points a week": starts * players.loc[after, "fpg"],
            }
        ).sort_values("Points a week", ascending=False),
        column_config={
            c: st.column_config.NumberColumn(format="%.1f")
            for c in ("FP/G", "Games a week", "Starts a week", "Points a week")
        },
        hide_index=True,
        width="stretch",
        height=ui.table_height(len(after)),
    )
