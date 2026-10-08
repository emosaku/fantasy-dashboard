"""The Trade Analyzer's Saved trades tab and Save trade buttons. The page brings the
scoring; this module stores (saved_store.py), checks, ranks and shows. A manager's saved
trades are read once per visit and kept in the session until they save or remove one.
"""

import datetime as dt
from collections.abc import Callable

import pandas as pd
import streamlit as st

import login
import saved_store
from saved_trades import FREE_AGENTS, SavedTrade, check, ids_of, make, rank


def _key(team_id: int) -> str:
    return f"saved-trades-{team_id}"


def _user() -> str:
    return login.current_user()["username"]


def load(team_id: int) -> list[SavedTrade]:
    key = _key(team_id)
    if key not in st.session_state:
        st.session_state[key] = saved_store.load(_user(), team_id)
    return st.session_state[key]


def save(team_id: int, source: str, labels: dict, partner, give, get,
         my_drop=None, their_drop=None, my_add=None, their_add=None) -> None:  # fmt: skip
    """Button callback. The arguments after `labels` are the ones the pages'
    load_into_mock takes, in its order."""
    trade = make(team_id, partner, give, get, my_add, my_drop, their_add, their_drop,
                 source, dt.datetime.now(dt.UTC), labels)  # fmt: skip
    saved_store.save(_user(), trade)
    st.session_state.pop(_key(team_id), None)
    st.toast("Saved. It's ranked with your others on the Saved trades tab.")


def remove(team_id: int, trade_id: str) -> None:
    saved_store.delete(_user(), trade_id)
    st.session_state.pop(_key(team_id), None)


def button(where, team_id: int, key: str, source: str, args: tuple,
           lookup: Callable) -> None:  # fmt: skip
    """A Save trade button. `args` are the ones the row's Load into mock trade takes
    (partner first); `lookup(player id)` gives the names kept with the trade."""
    players = {p for move in args[1:] for p in ids_of(move)}
    labels = {p: lookup(p) for p in players if lookup(p)}
    where.button("Save trade", key=f"save-{key}", icon=":material/bookmark_add:",
                 on_click=save, args=(team_id, source, labels, *args))  # fmt: skip


def owners(players: pd.DataFrame) -> dict:
    """Every player in today's data -> his team id, or FREE_AGENTS."""
    return {int(p): (FREE_AGENTS if pd.isna(t) else int(t)) for p, t in players["team_id"].items()}


def describe(trade: SavedTrade, lookup: Callable, team_label: Callable) -> str:
    """ "Waiver: add X, drop Y" or "With Team B: give X for Y", plus any other moves."""

    def names(ids) -> str:
        return ", ".join(trade.name(p, lookup) for p in ids) or "nobody"

    if trade.is_waiver:
        text = f"Waiver: add {names(trade.get)}"
        if trade.give:
            text += f", drop {names(trade.give)}"
    else:
        text = f"With {team_label(trade.partner)}: give {names(trade.give)} for {names(trade.get)}"
    extra = [
        f"{who} {verb} {names(ids)}"
        for who, verb, ids in (("you", "add", trade.my_add), ("you", "drop", trade.my_drop),
                               ("they", "add", trade.their_add),
                               ("they", "drop", trade.their_drop))
        if ids
    ]  # fmt: skip
    return text + (f" ({'; '.join(extra)})" if extra else "")


def section(team_id: int, players: pd.DataFrame, lookup: Callable,
            team_label: Callable, score: Callable, unit: str,
            open_in_mock: Callable) -> None:  # fmt: skip
    """The Saved trades tab: check every saved trade against today's rosters, remove the
    ones no longer possible (and say why), and rank the rest by `score(trade)`, which
    returns (your change, the partner's or None), or None when today's data can't
    score it."""
    keep, gone = check(load(team_id), owners(players))
    if gone:
        for trade, _ in gone:
            saved_store.delete(_user(), trade.id)
        st.session_state[_key(team_id)] = keep
        places = {"you": "your team", "free agents": "a free agent"}
        lines = []
        for trade, issues in gone:
            why = "; ".join(
                f"{trade.name(p, lookup)} is no longer "
                + ("" if where == "free agents" else "on ")
                + (places.get(where) or team_label(trade.partner))
                for p, where in issues
            )
            lines.append(f"- {describe(trade, lookup, team_label)}: {why}")
        st.warning(
            "Removed saved trades that roster changes made impossible:\n\n" + "\n".join(lines)
        )
    if not keep:
        st.info(
            "No saved trades yet. Save one from Waiver wire, Create a trade or Mock trade "
            "with its **Save trade** button."
        )
        return
    scores = {t.id: score(t) for t in keep}
    ranked = rank(keep, lambda t: None if scores[t.id] is None else scores[t.id][0])
    st.caption(
        f"Ranked by what each trade does for your team with today's data ({unit}), best "
        "first. A trade is removed once roster changes make it impossible."
    )
    for n, (trade, _) in enumerate(ranked, start=1):
        result = scores[trade.id]
        with st.container(border=True):
            head, b1, b2 = st.columns([6, 1.5, 1.1])
            head.markdown(f"**{n}. {describe(trade, lookup, team_label)}**")
            if result is None:
                head.caption("Can't be scored with today's data: a player in it isn't loaded.")
            else:
                mine, theirs = result
                text = f"You **{mine:+.2f}** {unit}"
                if theirs is not None:
                    text += f" · {team_label(trade.partner)} {theirs:+.2f}"
                head.markdown(text)
            when = f" on {trade.saved_at:%b %-d}" if trade.saved_at else ""
            head.caption(f"Saved from {trade.source}{when}")
            b1.button("Open in Mock trade", key=f"saved-open-{trade.id}", on_click=open_in_mock,
                      args=(trade,))  # fmt: skip
            b2.button("Remove", key=f"saved-remove-{trade.id}", on_click=remove,
                      args=(team_id, trade.id))  # fmt: skip
