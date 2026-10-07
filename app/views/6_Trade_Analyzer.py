"""Trade Analyzer page (Step 6): recommends waiver pickups and trades for one team,
ranked by how much each raises its expected all-play category wins (E), and keeps
the mock-trade simulator from the original proposal.

Controls: team (default team 10), stat window, swing size delta, per-category tier
overrides. Five tabs: Team profile, Waiver wire, Trade finder, Create a Trade, Mock
trade. Any waiver or trade row loads into Mock trade, which runs the same
simulation, so its numbers match the row's. Create a Trade has two ways in: search
by one player you want, or Offer Builder -- pick the players you'd move and it
proposes the best deals for them. Three-team deals (Unlock a player, or From my
trade block) search circles with two partners, and Mock trade can run one. The math
lives in app/analysis (tested); this page only lays it out. Reads v_player_z
(z-scores) and v_player_pool (per-game lines).
"""

import pandas as pd
import streamlit as st

import analyzer
import login
import queries
import ui
from analysis.explain import explain, group_pitch, pitch_text
from analysis.objective import expected_category_wins, matchup_record
from analysis.three_team import circle_moves, middle_plans, simulate_circle
from analysis.trades import (
    CLOSE_CALL,
    COSTS_YOU,
    LIKELY,
    MAX_GAIN,
    THEY_SAY_NO,
    WIN_WIN,
    as_ids,
    present,
    simulate_trade,
    top_targets,
    trade_chips,
)
from analysis.waivers import rank_pickups, rank_waiver_moves
from analysis.weights import compute_weights, player_values, punts
from categories import COLUMNS, LABELS, fmt
from categories import totals as totals_of
from health import games_by_season_text, health_text
from trade import trade_impact

st.title("Trade Analyzer")

names = analyzer.team_names()
windows = analyzer.available_windows()
if names.empty or not windows:
    st.info("No player data yet.")
    st.stop()

team_ids = [int(t) for t in names.index]
c1, c2, c3 = st.columns([1.6, 1, 1])
# Each manager analyzes their own team; the commissioner (admin) can pick any.
mine = login.my_team()
me = c1.selectbox(
    "Team",
    team_ids if login.is_admin() else [mine],
    index=team_ids.index(mine) if login.is_admin() and mine in team_ids else 0,
    format_func=names.get,
    disabled=not login.is_admin(),
    help=None if login.is_admin() else "Recommendations are for your own team.",
)
window = c2.selectbox("Stats from", windows, format_func=analyzer.STAT_WINDOWS.get)
delta = c3.number_input(
    "Swing size δ (z)",
    min_value=0.25,
    max_value=3.0,
    value=1.0,
    step=0.25,
    help="A realistic gain or loss in one category: 1.0 is about one solid starter.",
)

with st.expander("Category strategy: override tiers"):
    st.caption(
        "Auto picks Lock, Swing or Punt from the standings. Override any category: "
        "Lock and Swing change how much it counts, Punt drops it from your score."
    )
    grid = st.columns(3)
    choices = {
        col: grid[i % 3].selectbox(
            LABELS[col], ["Auto", "Lock", "Swing", "Punt"], key=f"tier-{me}-{col}"
        )
        for i, col in enumerate(COLUMNS)
    }
overrides = tuple(sorted((k, v) for k, v in choices.items() if v != "Auto"))

players, totals = analyzer.league(window)
if me not in totals.index:
    st.info("This team has no players with stats in this window.")
    st.stop()
weights = analyzer.weights_by_team(window, me, delta, overrides)
w_me = weights[me]
punts_me = punts(w_me)
player_name = players["player_name"]
max_e = len(COLUMNS) * (len(totals) - 1)


def team_label(team_id) -> str:
    return "Free agents" if team_id == 0 else names.get(team_id, str(team_id))


def names_of(ids) -> str:
    return ", ".join(player_name[i] for i in ids)


def cat_deltas(row, prefix="dE_") -> dict:
    return {col: row[f"{prefix}{col}"] for col in COLUMNS}


def keep_valid(key: str, options: list, multi: bool) -> None:
    """Drop a stored selection that no longer fits the options (e.g. after the
    partner changed), before the widget renders."""
    value = st.session_state.get(key)
    if value is None:
        return
    if multi:
        value = value if isinstance(value, list) else [value]
        st.session_state[key] = [v for v in value if v in options]
    elif value not in options:
        st.session_state[key] = None


def load_into_mock(partner, give, get, my_drop=None, their_drop=None, my_add=None, their_add=None):
    """Button callback: fill the Mock trade tab's controls with one deal. The
    partner's drop/add can be one player (most deals) or several (an uneven Offer
    Builder deal, e.g. a 3-for-1 where the partner must drop two to balance)."""
    st.session_state["mock-teams"] = 2
    st.session_state["mock-partner"] = int(partner)
    st.session_state["mock-give"] = [int(x) for x in give]
    st.session_state["mock-get"] = [int(x) for x in get]
    st.session_state["mock-my-drop"] = [int(x) for x in as_ids(my_drop)]
    st.session_state["mock-their-drop"] = [int(x) for x in as_ids(their_drop)]
    st.session_state["mock-my-add"] = [int(x) for x in as_ids(my_add)]
    st.session_state["mock-their-add"] = [int(x) for x in as_ids(their_add)]
    st.toast("Loaded. Open the Mock trade tab to see it.")


def load_circle_into_mock(circle, packages, my_drop=(), my_add=()) -> None:
    """Button callback: fill the Mock trade tab's three-team controls with a circle."""
    st.session_state["mock-teams"] = 3
    st.session_state["mock3-b"], st.session_state["mock3-c"] = int(circle[1]), int(circle[2])
    st.session_state["mock3-reverse"] = False
    for key, pack in zip(("mock3-send", "mock3-mid", "mock3-back"), packages, strict=True):
        st.session_state[key] = [int(x) for x in pack]
    st.session_state["mock3-my-drop"] = [int(x) for x in my_drop]
    st.session_state["mock3-my-add"] = [int(x) for x in my_add]
    st.toast("Loaded. Open the Mock trade tab to see it.")


def compare_players(ids) -> None:
    """Button callback: open Compare in Players mode with these players. Compare
    takes at most 4; an uneven Offer Builder deal can involve up to 6, so clip to
    the first 4 (give side first -- the players this manager is giving up)."""
    st.session_state["compare-players"] = [int(i) for i in ids][:4]
    st.switch_page("views/1_Compare.py")


profile_tab, waiver_tab, finder_tab, create_tab, mock_tab = st.tabs(
    ["Team profile", "Waiver wire", "Trade finder", "Create a trade", "Mock trade"]
)

# --- Team profile ------------------------------------------------------------------

with profile_tab:
    wins, losses, ties = matchup_record(totals, me)
    m1, m2 = st.columns(2)
    m1.metric(
        "Category wins vs everyone (E)",
        f"{expected_category_wins(totals, me, punts_me):g} of {max_e}",
        help="Categories won if you played all 13 other teams; ties count half. "
        "Punted categories don't count.",
    )
    m2.metric("All-play matchup record", f"{wins}-{losses}-{ties}")

    def tier_text(row) -> str:
        if row["tier"] == row["auto_tier"]:
            return row["tier"]
        return f"{row['tier']} (auto: {row['auto_tier']})"

    profile = w_me.assign(
        category=[LABELS[c] for c in w_me.index],
        tier_shown=w_me.apply(tier_text, axis=1),
    )
    st.dataframe(
        profile[["category", "rank", "total", "gap_above", "gap_below", "weight", "tier_shown"]],
        column_config={
            "category": "Category",
            "rank": st.column_config.NumberColumn("Rank", width="small"),
            "total": st.column_config.NumberColumn("Team z", format="%+.2f"),
            "gap_above": st.column_config.NumberColumn(
                "Gap to next team up", format="%.2f", help="z needed to pass the next team"
            ),
            "gap_below": st.column_config.NumberColumn("Lead over next team down", format="%.2f"),
            "weight": st.column_config.NumberColumn(
                "Weight", format="%.2f", help="How much this category counts (average 1.0)"
            ),
            "tier_shown": "Tier",
        },
        hide_index=True,
        width="stretch",
        height=ui.table_height(len(profile)),
    )
    st.caption(
        "Lock: top 3 and nobody within δ behind. Punt: bottom 3 and nobody within δ "
        "ahead. Swing: everything else, where a small gain flips matchups. Weights "
        "drive every recommendation on this page."
    )

# --- Waiver wire -------------------------------------------------------------------

with waiver_tab:
    st.caption(
        "Every free agent (top 100 on ESPN, none listed OUT) against every player you "
        "could drop (not on IR), ranked by the change in your category wins."
    )
    moves = rank_waiver_moves(players, totals, me, w_me)
    if moves.empty:
        st.info("No free agents to evaluate.")
    for k, move in moves.iterrows():
        title = f"Add {move['add_name']} · drop {move['drop_name']}: {move['dE']:+g} category wins"
        with st.expander(title):
            st.write(explain(cat_deltas(move)))
            dz = pd.Series({col: move[f"dz_{col}"] for col in COLUMNS})
            up, down = dz.idxmax(), dz.idxmin()
            st.caption(
                f"Biggest gain: {LABELS[up]} {dz[up]:+.2f} z · biggest cost: "
                f"{LABELS[down]} {dz[down]:+.2f} z · value to you Δv {move['dv']:+.2f} · "
                f"{move['add_name']} is {str(move['injury_status']).replace('_', ' ').lower()}"
            )
            wb1, wb2 = st.columns(2)
            wb1.button(
                "Load into mock trade",
                key=f"waiver-load-{k}",
                on_click=load_into_mock,
                args=(0, [move["drop_id"]], [move["add_id"]]),
            )
            wb2.button(
                "Compare players",
                key=f"waiver-compare-{k}",
                on_click=compare_players,
                args=([move["drop_id"], move["add_id"]],),
            )

# --- Trade finder ------------------------------------------------------------------

with finder_tab:
    st.caption(
        "Every 1-for-1 and 2-for-1 deal with every other team. Only win-win deals are "
        "kept: your category wins go up and theirs don't go down. Rosters stay full: "
        "whoever gets two players drops their least useful one, and whoever gives two "
        "picks up the best free agent for the open spot."
    )
    deals = analyzer.all_trades(window, me, delta, overrides)
    f1, f2 = st.columns([1, 2])
    hide_lopsided = f1.checkbox(
        "Hide lopsided deals",
        value=True,
        help="Lopsided: the players given and received differ by more than 1.5 in "
        "total z, so the other manager is unlikely to accept.",
    )
    sizes = f2.multiselect(
        "Deal sizes", ["1-for-1", "2-for-1", "1-for-2"], default=["1-for-1", "2-for-1", "1-for-2"]
    )
    if deals.empty:
        st.info("No win-win trades found.")
    else:
        shown = deals.assign(
            size=deals["give_ids"].map(len).astype(str)
            + "-for-"
            + deals["get_ids"].map(len).astype(str)
        )
        if hide_lopsided:
            shown = shown.loc[~shown["lopsided"]]
        shown = shown.loc[shown["size"].isin(sizes)].head(15)
        st.caption(f"{len(deals):,} win-win deals found; showing the best {len(shown)}.")
        for k, deal in shown.iterrows():
            title = (
                f"{team_label(deal['partner_id'])}: give {names_of(deal['give_ids'])} for "
                f"{names_of(deal['get_ids'])} · you {deal['dE_me']:+g}, them {deal['dE_them']:+g}"
                + (" · Lopsided" if deal["lopsided"] else "")
            )
            with st.expander(title):
                st.write(explain(cat_deltas(deal)))
                extra = []
                if present(deal["my_drop_id"]):
                    extra.append(f"you drop {player_name[deal['my_drop_id']]}")
                if present(deal["my_add_id"]):
                    extra.append(f"you pick up {player_name[deal['my_add_id']]} (free agent)")
                if present(deal["their_drop_id"]):
                    extra.append(f"they drop {player_name[deal['their_drop_id']]}")
                if present(deal["their_add_id"]):
                    extra.append(f"they pick up {player_name[deal['their_add_id']]} (free agent)")
                if extra:
                    st.caption("To keep rosters full: " + "; ".join(extra) + ".")
                st.caption(
                    f"General value (total z): you give {deal['gen_give']:+.2f}, "
                    f"you get {deal['gen_get']:+.2f}."
                )
                tb1, tb2 = st.columns(2)
                tb1.button(
                    "Load into mock trade",
                    key=f"trade-load-{k}",
                    on_click=load_into_mock,
                    args=(
                        deal["partner_id"],
                        deal["give_ids"],
                        deal["get_ids"],
                        deal["my_drop_id"],
                        deal["their_drop_id"],
                        deal["my_add_id"],
                        deal["their_add_id"],
                    ),
                )
                tb2.button(
                    "Compare players",
                    key=f"trade-compare-{k}",
                    on_click=compare_players,
                    args=([*deal["give_ids"], *deal["get_ids"]],),
                )

    t1, t2 = st.columns(2)
    with t1:
        st.subheader("Top targets")
        st.caption("Players on other rosters worth the most to you.")
        targets = top_targets(players, me, w_me)
        st.dataframe(
            targets.assign(team=targets["team_id"].map(lambda t: team_label(int(t))))[
                ["player_name", "team", "value", "generic"]
            ],
            column_config={
                "player_name": "Player",
                "team": "Team",
                "value": st.column_config.NumberColumn("Value to you", format="%+.2f"),
                "generic": st.column_config.NumberColumn("General value", format="%+.2f"),
            },
            hide_index=True,
            width="stretch",
        )
    with t2:
        st.subheader("Trade chips")
        st.caption("Your players worth more to others than to you.")
        chips = trade_chips(players, me, w_me)
        st.dataframe(
            chips[["player_name", "value", "generic"]],
            column_config={
                "player_name": "Player",
                "value": st.column_config.NumberColumn("Value to you", format="%+.2f"),
                "generic": st.column_config.NumberColumn("General value", format="%+.2f"),
            },
            hide_index=True,
            width="stretch",
        )

# --- Create a trade ----------------------------------------------------------------


def roster_moves(deal) -> str:
    """The add/drop moves that keep both rosters full, as a sentence (or "").
    Each field is one player id, None, or (Offer Builder, an uneven deal) several."""
    extra = []
    if as_ids(deal["my_drop_id"]):
        extra.append(f"you drop {names_of(as_ids(deal['my_drop_id']))}")
    if as_ids(deal["my_add_id"]):
        extra.append(f"you pick up {names_of(as_ids(deal['my_add_id']))} (free agent)")
    if as_ids(deal["their_drop_id"]):
        extra.append(f"they drop {names_of(as_ids(deal['their_drop_id']))}")
    if as_ids(deal["their_add_id"]):
        extra.append(f"they pick up {names_of(as_ids(deal['their_add_id']))} (free agent)")
    return ("To keep rosters full: " + "; ".join(extra) + ".") if extra else ""


VERDICT = {
    LIKELY: ":green-badge[Likely to work]",
    COSTS_YOU: ":orange-badge[Costs you]",
    THEY_SAY_NO: ":red-badge[They'd likely say no]",
}


def deal_card(deal, key: str) -> None:
    with st.container(border=True):
        st.markdown(
            f"{VERDICT[deal['status']]} Send **{names_of(deal['give_ids'])}** → get "
            f"**{names_of(deal['get_ids'])}**"
        )
        gap = deal["gen_get"] - deal["gen_give"]
        fairness = (
            "even value"
            if abs(gap) <= 0.5
            else (f"you get {gap:.1f} more value" if gap > 0 else f"you give {-gap:.1f} more value")
        )
        st.markdown(
            f"You **{deal['dE_me']:+g}** category wins · them **{deal['dE_them']:+g}** · {fairness}"
        )
        st.caption(explain(cat_deltas(deal)))
        moves = roster_moves(deal)
        if moves:
            st.caption(moves)
        db1, db2 = st.columns(2)
        db1.button(
            "Load into mock trade",
            key=key,
            on_click=load_into_mock,
            args=(
                deal["partner_id"],
                deal["give_ids"],
                deal["get_ids"],
                deal["my_drop_id"],
                deal["their_drop_id"],
                deal["my_add_id"],
                deal["their_add_id"],
            ),
        )
        db2.button(
            "Compare players",
            key=f"{key}-compare",
            on_click=compare_players,
            args=([*deal["give_ids"], *deal["get_ids"]],),
        )


# --- Three-team deals: the ESPN plan and the deal card -------------------------------


def who(team_id) -> str:
    return "You" if team_id == me else team_label(team_id)


def trade_text(middle, trade) -> str:
    s = "" if middle == me else "s"
    return (
        f"{who(middle)} ↔ {who(trade['with'])}: {who(middle)} send{s} "
        f"**{names_of(trade['middle_sends'])}**, get{s} **{names_of(trade['middle_gets'])}**"
    )


def risk_text(plan) -> str:
    middle = plan["middle"]
    verb = "are" if middle == me else "is"
    text = f"If trade 2 falls through, {who(middle)} {verb} at {plan['between']:+g} category wins."
    extra = plan["between_roster"]
    if extra > 0:
        text += (
            f" {who(middle)} need{'' if middle == me else 's'} {extra} open roster "
            f"spot{'s' if extra > 1 else ''} (or a drop) to accept trade 1."
        )
    elif extra < 0:
        text += (
            f" {who(middle)} {verb} {-extra} player{'s' if extra < -1 else ''} short until trade 2."
        )
    return text


def order_text(plan) -> str:
    """The group message's "easiest order", from my side."""
    m, first, second = plan["middle"], plan["trade1"]["with"], plan["trade2"]["with"]
    sends, gets = names_of(plan["trade2"]["middle_sends"]), names_of(plan["trade2"]["middle_gets"])
    if m == me:
        return (
            f"{team_label(first)} and I trade first, then I send {sends} to "
            f"{team_label(second)} for {gets}."
        )
    to = "me" if second == me else team_label(second)
    pair = f"{team_label(m)} and I" if first == me else f"{team_label(m)} and {team_label(first)}"
    return f"{pair} trade first, then {team_label(m)} sends {sends} to {to} for {gets}."


def trade_timing() -> list[str]:
    """Review-period and deadline notes for running two trades back to back."""
    status = queries.league_status()
    if status is None:
        return []
    notes = []
    hours = status.get("trade_review_hours")
    hours = None if hours is None or pd.isna(hours) else int(hours)
    if hours:
        notes.append(
            f"Each trade sits in a {hours}-hour review, and trade 2 can't be proposed until "
            f"trade 1 clears: about {2 * hours} hours for both."
        )
    deadline = status.get("trade_deadline")
    if deadline is not None and not pd.isna(deadline):
        deadline = pd.Timestamp(deadline)
        deadline = deadline.tz_localize("UTC") if deadline.tzinfo is None else deadline
        now = pd.Timestamp.now(tz="UTC")
        if now > deadline:
            notes.append("⚠️ The trade deadline has passed.")
        elif now + pd.Timedelta(hours=2 * (hours or 0)) > deadline:
            notes.append(
                f"⚠️ Both trades may not clear before the trade deadline "
                f"({deadline.tz_convert('America/Phoenix'):%b %-d, %-I:%M %p} AZ)."
            )
    return notes


def render_plans(plans: list[dict]) -> None:
    """The recommended way to run a circle on ESPN, then the other two."""
    best = plans[0]
    st.markdown(f"**Recommended: {who(best['middle'])} in the middle** (least exposed in between)")
    for n, trade in enumerate((best["trade1"], best["trade2"]), 1):
        st.markdown(f"{n}. {trade_text(best['middle'], trade)}")
    st.caption(risk_text(best))
    for n, trade in enumerate((best["trade1"], best["trade2"]), 1):
        if trade["lopsided"]:
            st.caption(
                f"Trade {n} looks lopsided on its own by player value, so league members "
                "could vote it down: present it as one three-team deal."
            )
    for note in trade_timing():
        st.caption(note)
    others = [
        f"{who(p['middle'])} in the middle: {p['between']:+g} for "
        f"{'you' if p['middle'] == me else team_label(p['middle'])} if trade 2 falls through"
        for p in plans[1:]
    ]
    st.caption("Other ways, same final rosters: " + "; ".join(others) + ".")


def fills_text(fills: dict) -> str:
    """Each team's drops and free-agent adds, as one sentence (or "")."""
    parts = []
    for team, (drops, adds) in fills.items():
        if drops:
            parts.append(f"{who(team)} drop{'' if team == me else 's'} {names_of(drops)}")
        if adds:
            parts.append(
                f"{who(team)} pick{'' if team == me else 's'} up {names_of(adds)} (free agent)"
            )
    return ("To keep rosters full: " + "; ".join(parts) + ".") if parts else ""


def three_team_card(deal, key: str) -> None:
    circle = deal["circle"]
    _, a, b = circle
    packages = (deal["give_ids"], deal["a_sends"], deal["get_ids"])
    moves = circle_moves(circle, packages)
    cats = {me: deal["cat_me"], a: deal["cat_a"], b: deal["cat_b"]}
    changes = {me: deal["dE_me"], a: deal["dE_a"], b: deal["dE_b"]}
    lopsided = {me: False, a: deal["lopsided_a"], b: deal["lopsided_b"]}
    with st.container(border=True):
        everyone = "all three gain" if min(changes.values()) > 0 else (
            f"{team_label(a)} {changes[a]:+g}, {team_label(b)} {changes[b]:+g}"
        )  # fmt: skip
        st.markdown(
            f"Get **{names_of(deal['get_ids'])}** · **{deal['dE_me']:+g} for you** · {everyone}"
        )
        st.dataframe(
            pd.DataFrame(
                {
                    "Team": [who(t) for t in circle],
                    "Sends": [names_of(moves[t][0]) for t in circle],
                    "Gets": [names_of(moves[t][1]) for t in circle],
                    "Category wins": [changes[t] for t in circle],
                    "Why": [explain(cats[t]) for t in circle],
                    "Flag": ["Lopsided" if lopsided[t] else "" for t in circle],
                }
            ),
            column_config={"Category wins": st.column_config.NumberColumn(format="%+g")},
            hide_index=True,
            width="stretch",
        )
        moves_text = fills_text(deal["fills"])
        if moves_text:
            st.caption(moves_text)
        plans = middle_plans(players, totals, circle, packages, weights)
        with st.expander("How to do it on ESPN"):
            render_plans(plans)
        with st.expander("Pitches"):
            for team in (a, b):
                st.markdown(f"**To {team_label(team)}**")
                st.code(pitch_text(cats[team]), language=None, wrap_lines=True)
            st.markdown("**One message for the group**")
            group = group_pitch(
                [("I", names_of(deal["get_ids"])), (team_label(a), names_of(deal["give_ids"])),
                 (team_label(b), names_of(deal["a_sends"]))],
                [(team_label(b), cats[b]), (team_label(a), cats[a])],
                order_text(plans[0]),
            )  # fmt: skip
            st.code(group, language=None, wrap_lines=True)
        my_drops, my_adds = deal["fills"].get(me, ((), ()))
        c1, c2 = st.columns(2)
        c1.button(
            "Load into mock trade",
            key=f"{key}-load",
            on_click=load_circle_into_mock,
            args=(circle, packages, my_drops, my_adds),
        )
        c2.button(
            "Compare players",
            key=f"{key}-compare",
            on_click=compare_players,
            args=([*deal["give_ids"], *deal["a_sends"], *deal["get_ids"]],),
        )


TT_ACCEPTANCE = {"Win-win": WIN_WIN, "Close call": CLOSE_CALL, "Max gain": MAX_GAIN}


def start_unlock(target_id: int) -> None:
    """Button callback: open the three-team search with this player loaded."""
    st.session_state["tt-mode"] = "Unlock a player"
    st.session_state["tt-target"] = int(target_id)
    st.session_state["tt-third"] = 0
    st.session_state["tt-acceptance"] = "Win-win"
    st.session_state["tt-params"] = {
        "mode": "unlock", "target": int(target_id), "third": None,
        "size": int(st.session_state.get("tt-size", 2)), "acceptance": WIN_WIN,
        "exclude": bool(st.session_state.get("tt-exclude", True)),
    }  # fmt: skip
    st.toast("Three-team deals for him are at the bottom of this tab.")


with create_tab:
    st.subheader("Offer Builder")
    st.caption(
        "Pick the players you're willing to move and (optionally) who with. Every "
        "deal built from them that raises your expected category wins comes back, "
        "ranked by how likely the other manager is to take it."
    )

    ANY_TEAM = 0  # sentinel: team ids here are always > 0

    def block_label(pid) -> str:
        row = players.loc[pid]
        note = ""
        positive_by_tier: dict[str, float] = {}
        for col in COLUMNS:
            if row[col] > 0:
                tier = w_me.at[col, "tier"]
                positive_by_tier[tier] = positive_by_tier.get(tier, 0.0) + row[col]
        if positive_by_tier:
            top_tier = max(positive_by_tier, key=positive_by_tier.get)
            if top_tier == "Punt":
                note = " (value mostly in your Punt categories)"
            elif top_tier == "Lock":
                note = " (value mostly in your Lock categories)"
        return f"{row['player_name']}{note}"

    block_options = [int(i) for i in players.index[(players["team_id"] == me) & ~players["is_ir"]]]
    block = st.multiselect(
        "Trade block",
        block_options,
        format_func=block_label,
        max_selections=6,
        key="offer-block",
        help="Players you're willing to trade away, up to 6. A note flags one whose "
        "value sits mostly in a category you've locked up or punted -- often the "
        "easiest to deal, since it costs you the least.",
    )

    b1, b2, b3 = st.columns(3)
    target_choice = b1.selectbox(
        "Target team",
        [ANY_TEAM, *team_ids],
        format_func=lambda t: "Any team" if t == ANY_TEAM else team_label(t),
        key="offer-target",
    )
    max_give_opts = [n for n in (1, 2, 3) if n <= len(block)] or [1, 2, 3]
    keep_valid("offer-max-give", max_give_opts, multi=False)
    if st.session_state.get("offer-max-give") is None:
        st.session_state["offer-max-give"] = max_give_opts[min(1, len(max_give_opts) - 1)]
    max_give = b2.selectbox(
        "Max players you give",
        max_give_opts,
        key="offer-max-give",
        help="Capped by how many players are in your trade block.",
    )
    max_get = b3.selectbox("Max players you get", [1, 2, 3], index=1, key="offer-max-get")

    acceptance_label = st.radio(
        "Acceptance level",
        ["Win-win", "Close call", "Max gain"],
        horizontal=True,
        key="offer-acceptance",
        help="Win-win: they don't lose either. Close call: costs them a little, but "
        "looks fair by value. Max gain: the ceiling, lopsided deals included -- "
        "expect most to be turned down.",
    )
    acceptance = {"Win-win": WIN_WIN, "Close call": CLOSE_CALL, "Max gain": MAX_GAIN}[
        acceptance_label
    ]
    with st.expander("Advanced"):
        exclude_injured = st.checkbox(
            "Exclude injured players I'd receive",
            value=True,
            key="offer-exclude-injured",
            help="Drops players listed OUT or on IR from the other side.",
        )
        allow_uneven = st.checkbox(
            "Allow uneven deals",
            value=True,
            key="offer-allow-uneven",
            help="Off: only sizes like 1-for-1 or 2-for-2, where you give and get "
            "the same number of players.",
        )

    if st.button("Find offers", type="primary", key="offer-find"):
        if not block:
            st.error("Pick at least one player you'd trade.")
        else:
            targets = (
                tuple(t for t in team_ids if t != me)
                if target_choice == ANY_TEAM
                else (int(target_choice),)
            )
            st.session_state["offer-params"] = (
                tuple(sorted(int(b) for b in block)),
                targets,
                int(max_give),
                int(max_get),
                acceptance,
                bool(exclude_injured),
                bool(allow_uneven),
            )
            st.session_state.pop("offer-show-targets", None)

    offer_params = st.session_state.get("offer-params")
    if offer_params is None:
        st.info("Pick at least one player you'd trade, then press **Find offers**.")
    else:
        pblock, ptargets, pmax_give, pmax_get, pacceptance, pexclude, puneven = offer_params
        deals, problem = analyzer.offers(
            window, me, pblock, ptargets, delta, overrides, pmax_give, pmax_get,
            pacceptance, pexclude, puneven,
        )  # fmt: skip
        if problem:
            st.error(problem)
        elif deals is None or deals.empty:
            st.info(
                "No deal with these players raises your category wins at this acceptance level."
            )
            e1, e2 = st.columns(2)
            next_level = {WIN_WIN: ("Close call", CLOSE_CALL), CLOSE_CALL: ("Max gain", MAX_GAIN)}
            if pacceptance in next_level:
                next_label, next_value = next_level[pacceptance]
                if e1.button(f"Try {next_label}", key="offer-try-next"):
                    st.session_state["offer-params"] = (
                        pblock, ptargets, pmax_give, pmax_get, next_value, pexclude, puneven,
                    )  # fmt: skip
                    st.rerun()
            if e2.button("Show top targets", key="offer-show-targets-btn"):
                st.session_state["offer-show-targets"] = True
            if st.session_state.get("offer-show-targets"):
                st.caption("Players on other rosters worth the most to you.")
                targets_df = top_targets(players, me, w_me)
                st.dataframe(
                    targets_df.assign(team=targets_df["team_id"].map(lambda t: team_label(int(t))))[
                        ["player_name", "team", "value", "generic"]
                    ],
                    column_config={
                        "player_name": "Player",
                        "team": "Team",
                        "value": st.column_config.NumberColumn("Value to you", format="%+.2f"),
                        "generic": st.column_config.NumberColumn("General value", format="%+.2f"),
                    },
                    hide_index=True,
                    width="stretch",
                )
        else:

            def cat_changes_text(row) -> str:
                vals = [(LABELS[c], row[f"dE_{c}"]) for c in COLUMNS]
                gains = sorted((v for v in vals if v[1] > 0), key=lambda v: -v[1])[:2]
                losses = sorted((v for v in vals if v[1] < 0), key=lambda v: v[1])[:1]
                left = ", ".join(f"+{label}" for label, _ in gains)
                right = ", ".join(f"{n:+g} {label}" for label, n in losses)
                return " / ".join(p for p in (left, right) if p) or "No category change"

            table = pd.DataFrame(
                {
                    "Team": [team_label(int(r.partner_id)) for r in deals.itertuples()],
                    "You give": [names_of(r.give_ids) for r in deals.itertuples()],
                    "You get": [names_of(r.get_ids) for r in deals.itertuples()],
                    "ΔE you": [r.dE_me for r in deals.itertuples()],
                    "ΔE them": [r.dE_them for r in deals.itertuples()],
                    "Your category changes": [cat_changes_text(row) for _, row in deals.iterrows()],
                    "Roster moves": [roster_moves(row) or "—" for _, row in deals.iterrows()],
                    "Flag": [
                        "Lopsided" if r.lopsided and pacceptance == MAX_GAIN else ""
                        for r in deals.itertuples()
                    ],
                }
            )
            st.caption(f"{len(deals)} offer{'s' if len(deals) != 1 else ''} found.")
            st.dataframe(
                table,
                column_config={
                    "ΔE you": st.column_config.NumberColumn(format="%+g"),
                    "ΔE them": st.column_config.NumberColumn(format="%+g"),
                },
                hide_index=True,
                width="stretch",
                height=ui.table_height(len(table)),
            )
            for k, deal in deals.iterrows():
                title = (
                    f"{team_label(deal['partner_id'])}: give {names_of(deal['give_ids'])} for "
                    f"{names_of(deal['get_ids'])} · you {deal['dE_me']:+g}, them "
                    f"{deal['dE_them']:+g}"
                )
                with st.expander(title):
                    st.markdown("**Why it helps you**")
                    st.write(explain(cat_deltas(deal)))
                    st.markdown("**The pitch** (to send the other manager)")
                    st.write(pitch_text(cat_deltas(deal, prefix="dEt_")))
                    moves = roster_moves(deal)
                    if moves:
                        st.caption(moves)
                    st.caption(
                        f"General value (total z): you give {deal['gen_give']:+.2f}, "
                        f"you get {deal['gen_get']:+.2f}."
                    )
                    ob1, ob2 = st.columns(2)
                    ob1.button(
                        "Load into mock trade",
                        key=f"offer-load-{k}",
                        on_click=load_into_mock,
                        args=(
                            deal["partner_id"],
                            deal["give_ids"],
                            deal["get_ids"],
                            deal["my_drop_id"],
                            deal["their_drop_id"],
                            deal["my_add_id"],
                            deal["their_add_id"],
                        ),
                    )
                    ob2.button(
                        "Compare players",
                        key=f"offer-compare-{k}",
                        on_click=compare_players,
                        args=([*deal["give_ids"], *deal["get_ids"]],),
                    )

    st.divider()
    st.subheader("Search by player")
    st.caption(
        "Pick a player you want. Every 1-for-1, 2-for-1, 1-for-2 and 2-for-2 deal that "
        "brings him to you is scored for both teams, and the ones the other manager is "
        "most likely to accept come first."
    )
    others = players.loc[
        players["team_id"].notna() & (players["team_id"] != me) & ~players["is_ir"]
    ]
    value_to_me = player_values(others, w_me).sort_values(ascending=False)

    def target_label(pid) -> str:
        row = players.loc[pid]
        text = f"{row['player_name']} · {row['position']} · {team_label(int(row['team_id']))}"
        if row["injury_status"] not in ("ACTIVE", None) and pd.notna(row["injury_status"]):
            text += f" · {str(row['injury_status']).replace('_', ' ').lower()}"
        return text

    p1, p2 = st.columns([1.4, 1])
    target = p1.selectbox(
        "Player you want",
        [int(i) for i in value_to_me.index],
        index=None,
        format_func=target_label,
        placeholder="Type a player's name...",
        filter_mode="contains",
        help="Players on other rosters, most valuable to your team first. Free agents "
        "are on the Waiver wire tab; players on IR aren't listed.",
    )
    all_sizes = ["1-for-1", "2-for-1", "1-for-2", "2-for-2"]
    create_sizes = p2.multiselect(
        "Deal sizes",
        all_sizes,
        default=all_sizes,
        key="create-sizes",
        help="1-for-2 and 2-for-2 bring back a second player from them as well.",
    )
    if target is None:
        st.info("Pick a player to see trades for him.")
    else:
        deals = analyzer.target_trades(window, me, target, delta, overrides)
        if not deals.empty:
            size = (
                deals["give_ids"].map(len).astype(str)
                + "-for-"
                + deals["get_ids"].map(len).astype(str)
            )
            deals = deals.loc[size.isin(create_sizes)]
        likely = deals.loc[deals["status"] == LIKELY] if not deals.empty else deals
        st.markdown(
            f"**{player_name[target]}** is worth {value_to_me[target]:+.2f} to you "
            f"(general value {players.loc[target, COLUMNS].sum():+.2f})."
        )
        if likely.empty:
            st.warning(
                "No deal both helps you and leaves the other team no worse off. The "
                "closest options are below."
            )
        else:
            st.subheader("Best offers")
            for k, deal in likely.head(5).iterrows():
                deal_card(deal, f"create-load-{k}")
        if len(likely) < 3 and not deals.empty:
            costs = deals.loc[deals["status"] == COSTS_YOU].head(2)
            no = deals.loc[deals["status"] == THEY_SAY_NO].head(2)
            if not costs.empty:
                st.subheader("What it would take")
                st.caption(
                    "They'd likely accept these, but they don't help your categories: "
                    "the price of getting him."
                )
                for k, deal in costs.iterrows():
                    deal_card(deal, f"create-load-{k}")
            if not no.empty:
                st.subheader("Good for you, harder to sell")
                st.caption(
                    "These help you, but cost them category wins or look lopsided by "
                    "player value, so expect pushback."
                )
                for k, deal in no.iterrows():
                    deal_card(deal, f"create-load-{k}")
        if deals.empty:
            st.info("No deal for him helps either team.")
        if len(likely) < 3:
            st.button(
                "Try a three-team deal",
                key="tt-shortcut",
                icon=":material/sync_alt:",
                on_click=start_unlock,
                args=(int(target),),
                help="Find a third team that makes a deal for him work for everyone.",
            )

    # --- Three-team deals ---
    st.divider()
    st.subheader("Three-team deals")
    st.caption(
        "Three packages move around a circle: you send to one partner, they send to the "
        "other, and the other sends to you. Each team is scored by its own needs and "
        "punts, and a deal is listed only if all three pass."
    )
    tt_mode = st.radio(
        "Mode", ["Unlock a player", "From my trade block"], horizontal=True, key="tt-mode"
    )
    unlock = tt_mode == "Unlock a player"
    if unlock:
        u1, u2 = st.columns([1.4, 1])
        keep_valid("tt-target", [int(i) for i in value_to_me.index], multi=False)
        tt_target = u1.selectbox(
            "Player you want",
            [int(i) for i in value_to_me.index],
            index=None,
            format_func=target_label,
            placeholder="Type a player's name...",
            filter_mode="contains",
            key="tt-target",
        )
        their_team = int(players.at[tt_target, "team_id"]) if tt_target is not None else None
        third_options = [ANY_TEAM, *[t for t in team_ids if t not in (me, their_team)]]
        keep_valid("tt-third", third_options, multi=False)
        tt_third = u2.selectbox(
            "Third team",
            third_options,
            format_func=lambda t: "Any team" if t == ANY_TEAM else team_label(t),
            key="tt-third",
            help="The team you send to, which sends on to his team.",
        )
    else:
        v1, v2 = st.columns([1.4, 1])
        tt_block = v1.multiselect(
            "Trade block",
            block_options,
            format_func=block_label,
            max_selections=6,
            key="tt-block",
            help="Players you're willing to trade away, up to 6.",
        )
        tt_partners = v2.multiselect(
            "Partners",
            [t for t in team_ids if t != me],
            format_func=team_label,
            max_selections=2,
            key="tt-partners",
            placeholder="Any two teams",
            help="Leave empty for any two teams, or name one or two.",
        )
    w1, w2 = st.columns(2)
    tt_size = w1.radio(
        "Players per package", [1, 2], index=1, horizontal=True, key="tt-size",
        help="How many players each team sends, at most.",
    )  # fmt: skip
    tt_acceptance_label = w2.radio(
        "Acceptance", list(TT_ACCEPTANCE), horizontal=True, key="tt-acceptance",
        help="Applies to both partners. Win-win: neither loses category wins. Close call: "
        "each may lose up to 2. Max gain: no limit, lopsided deals flagged.",
    )  # fmt: skip
    with st.expander("Advanced"):
        if unlock:
            tt_exclude = st.checkbox(
                "Skip injured players you'd receive", value=True, key="tt-exclude",
                help="Leaves out his teammates listed OUT.",
            )  # fmt: skip
        else:
            tt_shortlist = st.slider(
                "Partner shortlist", 4, 8, 6, key="tt-shortlist",
                help="How many of each partner's most movable players the search tries: "
                "those worth less to their own team than in general, never OUT.",
            )  # fmt: skip

    if st.button("Find three-team deals", type="primary", key="tt-find"):
        if unlock and tt_target is None:
            st.error("Pick the player you want.")
        elif not unlock and not tt_block:
            st.error("Pick at least one player you'd trade.")
        elif unlock:
            st.session_state["tt-params"] = {
                "mode": "unlock", "target": int(tt_target),
                "third": None if tt_third == ANY_TEAM else int(tt_third), "size": int(tt_size),
                "acceptance": TT_ACCEPTANCE[tt_acceptance_label], "exclude": bool(tt_exclude),
            }  # fmt: skip
        else:
            st.session_state["tt-params"] = {
                "mode": "block", "block": tuple(sorted(int(b) for b in tt_block)),
                "partners": tuple(int(x) for x in tt_partners), "size": int(tt_size),
                "acceptance": TT_ACCEPTANCE[tt_acceptance_label], "shortlist": int(tt_shortlist),
            }  # fmt: skip

    params = st.session_state.get("tt-params")
    if params is None:
        st.info("Set up a search, then press **Find three-team deals**.")
    else:
        if params["mode"] == "unlock":
            two_team = analyzer.target_trades(window, me, params["target"], delta, overrides)
            likely_two = (
                two_team.loc[two_team["status"] == LIKELY] if not two_team.empty else two_team
            )
            best_two = float(likely_two["dE_me"].max()) if not likely_two.empty else 0.0
            tt_deals, problem = analyzer.three_team_for_target(
                window, me, params["target"], delta, overrides, params["third"],
                params["size"], params["acceptance"], params["exclude"], best_two,
            )  # fmt: skip
            st.markdown(f"Deals for **{player_name[params['target']]}**.")
            st.caption(
                f"Best two-team deal: {best_two:+g}, likely to work. Three-team deals are "
                "listed only when they beat it, since two trades are harder to land than one."
                if not likely_two.empty
                else "No two-team deal for him is likely to work."
            )
        else:
            tt_deals, problem = analyzer.three_team_offers(
                window, me, params["block"], params["partners"], delta, overrides,
                params["size"], params["acceptance"], params["shortlist"],
            )  # fmt: skip
        if problem:
            st.error(problem)
        elif tt_deals is None or tt_deals.empty:
            st.info("No three-team deal passes for all three teams at this acceptance level.")
            n1, n2 = st.columns(2)
            next_level = {WIN_WIN: ("Close call", CLOSE_CALL), CLOSE_CALL: ("Max gain", MAX_GAIN)}
            if params["acceptance"] in next_level:
                label_next, value_next = next_level[params["acceptance"]]
                if n1.button(f"Try {label_next}", key="tt-try-next"):
                    st.session_state["tt-params"] = params | {"acceptance": value_next}
                    st.rerun()
            if params["mode"] == "block" and params["shortlist"] < 8:
                if n2.button("Try a longer partner shortlist", key="tt-longer"):
                    st.session_state["tt-params"] = params | {"shortlist": 8}
                    st.rerun()
        else:
            st.caption(
                f"{len(tt_deals)} deal{'s' if len(tt_deals) != 1 else ''} found, at most 2 "
                "from any pair of partners."
            )
            for k, deal in tt_deals.iterrows():
                three_team_card(deal, f"tt-{k}")

# --- Mock trade --------------------------------------------------------------------


def per_game_lines(window: str) -> pd.DataFrame:
    """Raw per-game lines for the per-game table. Blended has no raw line of its own,
    so it uses each player's season stats once he has them, else his projection."""
    pool = queries.player_pool()
    if window != "blended":
        return pool.loc[pool["stat_window"] == window]
    pool = pool.loc[pool["stat_window"].isin(["season", "projected"])]
    return pool.sort_values("stat_window", ascending=False).drop_duplicates("player_id")


def deal_players(moves: list[tuple[int, str]]) -> None:
    """Health, games played and per-game line of every player in a deal."""
    st.subheader("Players in this deal")
    profile = queries.player_profile().set_index("player_id")
    deal_lines = per_game_lines(window).set_index("player_id")

    def health(pid) -> str:
        return health_text(profile.loc[pid]) if pid in profile.index else ""

    def games_by_season(pid) -> str:
        return games_by_season_text(profile.loc[pid]) if pid in profile.index else ""

    deal_rows = []
    for pid, move in moves:
        # One player's 9 categories: percentages from his makes / attempts.
        line = totals_of(deal_lines.loc[[pid]]) if pid in deal_lines.index else None
        avg_gp = profile.at[pid, "avg_games_played"] if pid in profile.index else None
        deal_rows.append(
            {
                "Move": move,
                "Player": player_name[pid],
                "Health": health(pid),
                "Avg games (3 yrs)": avg_gp,
                "Games by season": games_by_season(pid),
                **{LABELS[c]: fmt(c, line[c]) if line is not None else "–" for c in COLUMNS},
            }
        )
    st.dataframe(
        pd.DataFrame(deal_rows),
        column_config={
            "Avg games (3 yrs)": st.column_config.NumberColumn(
                format="%.1f",
                help="Average games played over the last 3 seasons he was in the NBA",
            ),
            "Games by season": st.column_config.TextColumn(
                help="Games played three, two and one seasons ago (– = not in the NBA)"
            ),
        },
        hide_index=True,
        width="stretch",
    )
    st.caption(
        f"Per-game stats from: {analyzer.STAT_WINDOWS.get(window, window)}"
        + (
            " (season averages once a player has them, else ESPN's projection)."
            if window == "blended"
            else "."
        )
        + " Health is ESPN's status; it doesn't give injury type."
    )
    outlooks = [
        (player_name[pid], profile.at[pid, "season_outlook"])
        for pid, _ in moves
        if pid in profile.index and pd.notna(profile.at[pid, "season_outlook"])
    ]
    if outlooks:
        with st.expander("ESPN outlook for these players"):
            for name, outlook in outlooks:
                st.markdown(f"**{name}:** {outlook}")


def side_report(team_id, result, team_overrides, team_punts, after) -> None:
    before_w = compute_weights(totals, team_id, delta, team_overrides)
    after_w = compute_weights(after, team_id, delta, team_overrides)
    e0 = expected_category_wins(totals, team_id, team_punts)
    e1 = expected_category_wins(after, team_id, team_punts)
    rec0, rec1 = matchup_record(totals, team_id), matchup_record(after, team_id)
    st.markdown(f"**{team_label(team_id)}**")
    a, b = st.columns(2)
    a.metric("Category wins (E)", f"{e1:g}", f"{e1 - e0:+g}")
    b.metric("Matchup record", "-".join(map(str, rec1)))
    b.caption(f"was {'-'.join(map(str, rec0))}")
    st.write(explain(result.cat_delta))

    def arrow(x0, x1) -> str:
        return str(x0) if x0 == x1 else f"{x0} → {x1}"

    table = pd.DataFrame(
        {
            "Category": [LABELS[c] for c in COLUMNS],
            "Rank": [arrow(before_w.at[c, "rank"], after_w.at[c, "rank"]) for c in COLUMNS],
            "Tier": [arrow(before_w.at[c, "tier"], after_w.at[c, "tier"]) for c in COLUMNS],
            "z ±": [after.at[team_id, c] - totals.at[team_id, c] for c in COLUMNS],
            "Wins ±": [result.cat_delta[c] for c in COLUMNS],
        }
    )
    st.dataframe(
        table,
        column_config={
            "z ±": st.column_config.NumberColumn(
                format="%+.2f", help="Change in team z (sum of player z-scores)"
            ),
            "Wins ±": st.column_config.NumberColumn(
                format="%+g", help="Change in categories won against the other 13 teams"
            ),
        },
        hide_index=True,
        width="stretch",
        height=ui.table_height(len(table)),
    )


def per_game_totals(changes: list[tuple[int, list, list]]) -> None:
    """Per-game roster totals before and after, one table per (team, out, in)."""
    with st.expander("Per-game totals before and after"):
        lines = per_game_lines(window).set_index("player_id", drop=False)
        c = ui.colors()

        def delta_cell(col: str, value: float) -> str:
            if pd.isna(value) or abs(value) < 1e-9:
                return "–"
            text = f"{value:+.3f}".replace("0.", ".") if col.endswith("_pct") else f"{value:+.1f}"
            return f"▲ {text}" if value > 0 else f"▼ {text}"

        def color(cell: str) -> str:
            if cell.startswith("▲"):
                return f"color: {c['up']}"
            if cell.startswith("▼"):
                return f"color: {c['down']}"
            return ""

        st.caption("Per-game roster totals, IR excluded. ▲ is better in every category.")
        for column, (team_id, out_ids, in_ids) in zip(
            st.columns(len(changes)), changes, strict=True
        ):
            roster = lines.loc[lines["team_id"] == team_id]
            receiving = lines.loc[[i for i in in_ids if i in lines.index]]
            impact = trade_impact(roster, list(out_ids), receiving)
            table = pd.DataFrame(
                {
                    "Category": [LABELS[col] for col in COLUMNS],
                    "Before": [fmt(col, impact.at[col, "before"]) for col in COLUMNS],
                    "After": [fmt(col, impact.at[col, "after"]) for col in COLUMNS],
                    "Change": [delta_cell(col, impact.at[col, "delta"]) for col in COLUMNS],
                }
            )
            with column:
                st.markdown(f"**{who(team_id)}**")
                st.dataframe(
                    table.style.map(color, subset=["Change"]), hide_index=True, width="stretch"
                )


def player_label(pid) -> str:
    if pid is None:
        return "Nobody"
    return f"{player_name[pid]}{' (IR)' if players.at[pid, 'is_ir'] else ''}"


def roster_of(team_id) -> list[int]:
    return [int(i) for i in players.index[players["team_id"] == team_id]]


def mock_three() -> None:
    """The three-team Mock trade: a circle with two partners."""
    st.caption(
        "Three packages move around a circle: you send to the first partner, the first "
        "sends to the second, and the second sends to you. Partners keep their rosters full "
        "automatically (drop their least useful player, or pick up the best free agent); "
        "your own adds and drops are yours to pick."
    )
    partner_ids = [t for t in team_ids if t != me]
    keep_valid("mock3-b", partner_ids, multi=False)
    if st.session_state.get("mock3-b") is None:
        st.session_state["mock3-b"] = partner_ids[0]
    c1, c2, c3 = st.columns([1, 1, 0.8])
    b = c1.selectbox("Partner 1", partner_ids, format_func=team_label, key="mock3-b")
    c_options = [t for t in partner_ids if t != b]
    keep_valid("mock3-c", c_options, multi=False)
    if st.session_state.get("mock3-c") is None:
        st.session_state["mock3-c"] = c_options[0]
    c = c2.selectbox("Partner 2", c_options, format_func=team_label, key="mock3-c")
    reverse = c3.toggle("Reverse direction", key="mock3-reverse", help="Send to Partner 2 instead.")
    first, second = (c, b) if reverse else (b, c)
    circle = (me, first, second)
    mine_ids, first_ids, second_ids = roster_of(me), roster_of(first), roster_of(second)
    for key, ids in (("mock3-send", mine_ids), ("mock3-mid", first_ids),
                     ("mock3-back", second_ids)):  # fmt: skip
        keep_valid(key, ids, multi=True)
    s1, s2, s3 = st.columns(3)
    send = s1.multiselect(f"You send to {team_label(first)}", mine_ids,
                          format_func=player_label, key="mock3-send")  # fmt: skip
    mid = s2.multiselect(f"{team_label(first)} sends to {team_label(second)}", first_ids,
                         format_func=player_label, key="mock3-mid")  # fmt: skip
    back = s3.multiselect(f"{team_label(second)} sends to you", second_ids,
                          format_func=player_label, key="mock3-back")  # fmt: skip

    st.markdown("**Your other moves**")
    fa_ids = [int(i) for i in players.index[players["is_free_agent"]]]
    m1, m2 = st.columns(2)
    add_options = [i for i in fa_ids if i not in back]
    drop_options = [i for i in mine_ids if i not in send]
    keep_valid("mock3-my-add", add_options, multi=True)
    keep_valid("mock3-my-drop", drop_options, multi=True)
    my_add = m1.multiselect("Add free agents", add_options, format_func=player_label,
                            key="mock3-my-add")  # fmt: skip
    my_drop = m2.multiselect("Drop players", drop_options, format_func=player_label,
                             key="mock3-my-drop")  # fmt: skip
    size_now = len(mine_ids)
    size_after = size_now - len(send) + len(back) - len(my_drop) + len(my_add)
    if size_after == size_now:
        st.caption(f"Your roster: {size_now} players before and after. ✓")
    else:
        fix = (f"drop {size_after - size_now} more" if size_after > size_now
               else f"add {size_now - size_after} more")  # fmt: skip
        st.caption(f"Your roster: {size_now} → {size_after} players. To stay at {size_now}, {fix}.")
    if not send and not mid and not back:
        st.info("Pick players to see the result.")
        return

    empty = analyzer.empty_slot(window)
    packages = (tuple(send), tuple(mid), tuple(back))
    result = simulate_circle(players, totals, circle, packages, weights, my_drop=my_drop,
                             my_add=my_add, fill_mine=False, empty=empty)  # fmt: skip
    partner_fills = {t: result.fills[t] for t in circle[1:]}
    if fills_text(partner_fills):
        st.caption(fills_text(partner_fills))

    def add_suggestion(add_id, drop_id) -> None:
        st.session_state["mock3-my-add"] = [*st.session_state.get("mock3-my-add", []), add_id]
        if present(drop_id):
            st.session_state["mock3-my-drop"] = [
                *st.session_state.get("mock3-my-drop", []), int(drop_id),
            ]  # fmt: skip

    open_spot = size_after < size_now
    if st.button(
        "Suggest a pickup",
        icon=":material/person_add:",
        key="mock3-suggest-btn",
        help="Free agents ranked by what they add to your team after this move.",
    ):
        st.session_state["mock3-suggest"] = True
    if st.session_state.get("mock3-suggest"):
        partner_adds = [p for t in circle[1:] for p in result.fills[t][1]]
        picks = rank_pickups(
            players, result.after, me, w_me,
            [i for i in mine_ids if i not in send and i not in my_drop],
            exclude=[*back, *my_add, *partner_adds], add_only=open_spot, top=5, empty=empty,
        )  # fmt: skip
        with st.container(border=True):
            head, hide = st.columns([4, 1])
            head.markdown("**Best pickups after this move**"
                          + (" (you have an open roster spot)" if open_spot else ""))  # fmt: skip
            if hide.button("Hide", key="mock3-suggest-hide"):
                st.session_state["mock3-suggest"] = False
                st.rerun()
            if picks.empty:
                st.caption("No free agent helps here.")
            for i, pick in picks.iterrows():
                text = f"Add **{pick['add_name']}**"
                if present(pick["drop_id"]):
                    text += f" · drop **{pick['drop_name']}**"
                left, right = st.columns([4, 1])
                left.markdown(text + f": {pick['dE']:+g} category wins")
                left.caption(explain(cat_deltas(pick)))
                right.button("Add to move", key=f"mock3-suggest-{i}", on_click=add_suggestion,
                             args=(int(pick["add_id"]), pick["drop_id"]))  # fmt: skip

    if my_add or my_drop:
        deal_only = simulate_circle(players, totals, circle, packages, weights,
                                    fill_mine=False, empty=empty)  # fmt: skip
        e_now = expected_category_wins(totals, me, punts_me)
        rows = []
        for name, state in (("Now", totals), ("Deal only", deal_only.after),
                            ("Deal + your moves", result.after)):  # fmt: skip
            e = expected_category_wins(state, me, punts_me)
            rows.append({
                "": name,
                "Category wins (E)": f"{e:g}" + ("" if name == "Now" else f" ({e - e_now:+g})"),
                "Matchup record": "-".join(map(str, matchup_record(state, me))),
            })  # fmt: skip
        st.markdown("**Step by step**")
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    st.subheader("How to do it on ESPN")
    render_plans(middle_plans(players, totals, circle, packages, weights))

    moves = circle_moves(circle, packages)
    deal_moves = [(pid, f"You send to {team_label(first)}") for pid in send]
    deal_moves += [(pid, f"{team_label(first)} sends to {team_label(second)}") for pid in mid]
    deal_moves += [(pid, "You get") for pid in back]
    deal_moves += [(pid, "You also drop") for pid in my_drop]
    deal_moves += [(pid, "You pick up") for pid in my_add]
    for t in circle[1:]:
        drops, adds = result.fills[t]
        deal_moves += [(pid, f"{team_label(t)} drops") for pid in drops]
        deal_moves += [(pid, f"{team_label(t)} picks up") for pid in adds]
    deal_players(deal_moves)

    st.subheader("Results")
    for tab, team in zip(st.tabs([who(t) for t in circle]), circle, strict=True):
        with tab:
            side_report(team, result.sides[team], dict(overrides) if team == me else None,
                        punts(weights[team]), result.after)  # fmt: skip
    changes = []
    for team in circle:
        sent, got = moves[team]
        drops, adds = result.fills[team]
        changes.append((team, [*sent, *drops], [*got, *adds]))
    per_game_totals(changes)


with mock_tab:
    mock_teams = st.radio(
        "Teams in the deal", [2, 3], horizontal=True, key="mock-teams",
        help="3: a three-team deal around a circle.",
    )  # fmt: skip
    if mock_teams == 3:
        mock_three()
        st.stop()
    st.caption(
        "Try any deal, or load one from the other tabs. Pick Free agents as the "
        "partner to try a pickup: what you send is dropped, what you get is added."
    )
    partner_options = [0, *[t for t in team_ids if t != me]]
    keep_valid("mock-partner", partner_options, multi=False)
    if st.session_state.get("mock-partner") is None:  # first visit: another team
        st.session_state["mock-partner"] = partner_options[min(1, len(partner_options) - 1)]
    partner = st.selectbox(
        "Trade with", partner_options, format_func=team_label, key="mock-partner"
    )
    is_waiver = partner == 0

    my_ids = [int(i) for i in players.index[players["team_id"] == me]]
    if is_waiver:
        their_ids = [int(i) for i in players.index[players["is_free_agent"]]]
    else:
        their_ids = [int(i) for i in players.index[players["team_id"] == partner]]
    fa_ids = [int(i) for i in players.index[players["is_free_agent"]]]

    def label(pid) -> str:
        if pid is None:
            return "Nobody"
        tag = " (IR)" if players.at[pid, "is_ir"] else ""
        return f"{player_name[pid]}{tag}"

    keep_valid("mock-give", my_ids, multi=True)
    keep_valid("mock-get", their_ids, multi=True)
    g1, g2 = st.columns(2)
    give = g1.multiselect(
        "You drop" if is_waiver else "You send", my_ids, format_func=label, key="mock-give"
    )
    get = g2.multiselect(
        "You add" if is_waiver else "You get", their_ids, format_func=label, key="mock-get"
    )

    # --- Your other moves: free agents added and players dropped around the deal ---
    st.markdown("**Your other moves**")
    m1, m2 = st.columns(2)
    my_add_opts = [i for i in fa_ids if i not in get]
    my_drop_opts = [i for i in my_ids if i not in give]
    keep_valid("mock-my-add", my_add_opts, multi=True)
    keep_valid("mock-my-drop", my_drop_opts, multi=True)
    my_add = m1.multiselect("Add free agents", my_add_opts, format_func=label, key="mock-my-add")
    my_drop = m2.multiselect("Drop players", my_drop_opts, format_func=label, key="mock-my-drop")

    their_drop = their_add = []
    if not is_waiver:
        with st.expander(f"{team_label(partner)}'s roster moves (optional)"):
            r1, r2 = st.columns(2)
            their_drop_opts = [i for i in their_ids if i not in get]
            their_add_opts = [i for i in fa_ids if i not in my_add]
            keep_valid("mock-their-drop", their_drop_opts, multi=True)
            keep_valid("mock-their-add", their_add_opts, multi=True)
            their_drop = r1.multiselect(
                "They also drop", their_drop_opts, format_func=label, key="mock-their-drop"
            )
            their_add = r2.multiselect(
                "They also pick up", their_add_opts, format_func=label, key="mock-their-add"
            )

    # Roster after the whole move (in waiver mode `give` are drops and `get` adds).
    roster_after = [
        *[i for i in my_ids if i not in give and i not in my_drop],
        *get,
        *my_add,
    ]
    size_now, size_after = len(my_ids), len(roster_after)
    if size_after == size_now:
        st.caption(f"Your roster: {size_now} players before and after. ✓")
    else:
        fix = (
            f"drop {size_after - size_now} more"
            if size_after > size_now
            else f"add {size_now - size_after} more"
        )
        st.caption(f"Your roster: {size_now} → {size_after} players. To stay at {size_now}, {fix}.")

    if not give and not get and not my_add and not my_drop:
        st.info("Pick players to see the result.")
        st.stop()

    them = None if is_waiver else partner
    punts_them = () if is_waiver else punts(weights[partner])
    empty = analyzer.empty_slot(window)
    after, mine, theirs = simulate_trade(
        players,
        totals,
        me,
        them,
        give,
        get,
        my_drop,
        their_drop,
        my_add,
        their_add,
        punts_me,
        punts_them,
        empty,
    )

    # --- Suggest a pickup, for the roster this move leaves you ---
    def add_suggestion(add_id, drop_id) -> None:
        """Button callback: put a suggested add (and drop) into the move."""
        st.session_state["mock-my-add"] = [*st.session_state.get("mock-my-add", []), add_id]
        if present(drop_id):
            st.session_state["mock-my-drop"] = [
                *st.session_state.get("mock-my-drop", []),
                int(drop_id),
            ]

    open_spot = size_after < size_now
    if st.button(
        "Suggest a pickup",
        icon=":material/person_add:",
        help="Free agents ranked by what they add to your team after this move: a plain "
        "add if the move leaves a roster spot open, otherwise an add-and-drop.",
    ):
        st.session_state["mock-suggest"] = True
    if st.session_state.get("mock-suggest"):
        picks = rank_pickups(
            players,
            after,
            me,
            w_me,  # your strategy, not one recomputed from a half-finished roster
            [i for i in my_ids if i not in give and i not in my_drop],  # never one just received
            exclude=[*get, *my_add, *as_ids(their_add)],
            add_only=open_spot,
            top=5,
            empty=empty,
        )
        with st.container(border=True):
            head, hide = st.columns([4, 1])
            head.markdown(
                "**Best pickups after this move**"
                + (" (you have an open roster spot)" if open_spot else "")
            )
            if hide.button("Hide", key="mock-suggest-hide"):
                st.session_state["mock-suggest"] = False
                st.rerun()
            if picks.empty:
                st.caption("No free agent helps here.")
            for i, pick in picks.iterrows():
                text = f"Add **{pick['add_name']}**"
                if present(pick["drop_id"]):
                    text += f" · drop **{pick['drop_name']}**"
                text += f": {pick['dE']:+g} category wins"
                if pd.notna(pick["injury_status"]) and pick["injury_status"] != "ACTIVE":
                    text += f" ({str(pick['injury_status']).replace('_', ' ').lower()})"
                left, right = st.columns([4, 1])
                left.markdown(text)
                left.caption(explain(cat_deltas(pick)))
                right.button(
                    "Add to move",
                    key=f"mock-suggest-{i}",
                    on_click=add_suggestion,
                    args=(int(pick["add_id"]), pick["drop_id"]),
                )

    # --- What the trade does on its own, and with your other moves ---
    if (give or get) and (my_add or my_drop):
        trade_only, _, _ = simulate_trade(
            players, totals, me, them, give, get, None, their_drop, None, their_add, empty=empty
        )
        stages = [("Now", totals), ("Trade only", trade_only), ("Trade + your moves", after)]
        e_now = expected_category_wins(totals, me, punts_me)
        rows = []
        for name, state in stages:
            e = expected_category_wins(state, me, punts_me)
            rows.append(
                {
                    "": name,
                    "Category wins (E)": f"{e:g}" + ("" if name == "Now" else f" ({e - e_now:+g})"),
                    "Matchup record": "-".join(map(str, matchup_record(state, me))),
                }
            )
        st.markdown("**Step by step**")
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    moves = [(pid, "You drop" if is_waiver else "You send") for pid in give]
    moves += [(pid, "You add" if is_waiver else "You get") for pid in get]
    moves += [(pid, "You also drop") for pid in my_drop]
    moves += [(pid, "You pick up") for pid in my_add]
    moves += [(pid, "They drop") for pid in their_drop]
    moves += [(pid, "They pick up") for pid in their_add]
    deal_players(moves)

    s1, s2 = st.columns(2)
    with s1:
        side_report(me, mine, dict(overrides), punts_me, after)
    if theirs is not None:
        with s2:
            side_report(partner, theirs, None, punts_them, after)

    changes = [(me, [*give, *my_drop], [*get, *my_add])]
    if not is_waiver:
        changes.append((partner, [*get, *their_drop], [*give, *their_add]))
    per_game_totals(changes)
