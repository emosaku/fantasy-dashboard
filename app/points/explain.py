"""Plain-language summaries of points deals: why a deal helps a team, and a pitch
written from the other manager's side. Counted straight from the numbers, never
written by a model. Pure pandas."""

import pandas as pd


def player_text(players: pd.DataFrame, pid) -> str:
    p = players.loc[pid]
    return f"{p['player_name']} ({p['fpg']:.1f} FP/G, {p['games']:.1f} games a week)"


def names(players: pd.DataFrame, ids) -> str:
    return ", ".join(players.at[i, "player_name"] for i in ids) or "nobody"


def listing(players: pd.DataFrame, ids) -> str:
    items = [player_text(players, i) for i in ids]
    if len(items) <= 1:
        return "".join(items) or "nobody"
    return ", ".join(items[:-1]) + " and " + items[-1]


def change_text(d_wins: float, d_points: float) -> str:
    return f"{d_wins:+.2f} wins a week ({d_points:+.1f} points a week)"


def roster_moves(players: pd.DataFrame, adds, drops, you: bool = True) -> str:
    """ "To keep the roster full: drop X; pick up Y (free agent)." or ""."""
    parts = []
    if drops:
        parts.append(("drop " if you else "they drop ") + names(players, drops))
    if adds:
        parts.append(
            ("pick up " if you else "they pick up ") + names(players, adds) + " (free agent)"
        )
    return ("To keep the roster full: " + "; ".join(parts) + ".") if parts else ""


def why(players: pd.DataFrame, deal) -> str:
    """Why a deal helps me, in one paragraph."""
    text = (
        f"{change_text(deal['dE_me'], deal['dmu_me'])}. You get "
        f"{listing(players, deal['get_ids'])} for {listing(players, deal['give_ids'])}."
    )
    moves = roster_moves(players, deal["my_add_ids"], deal["my_drop_ids"])
    return f"{text} {moves}".strip()


def pitch(players: pd.DataFrame, deal) -> str:
    """The deal from the other manager's side, ready to send."""
    gain = deal["dmu_them"]
    head = (
        f"This adds about {gain:.1f} points a week to your lineup"
        if gain > 0.05
        else "This keeps your lineup about level"
    )
    text = (
        f"{head}: you'd get {listing(players, deal['give_ids'])} for "
        f"{listing(players, deal['get_ids'])}."
    )
    if deal["their_add_ids"]:
        text += (
            f" Your open spot can go to {names(players, deal['their_add_ids'])}, "
            "the best free agent."
        )
    if deal["their_drop_ids"]:
        text += f" You'd drop {names(players, deal['their_drop_ids'])} to make room."
    return text
