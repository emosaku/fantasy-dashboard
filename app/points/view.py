"""Small helpers every points page shares: the header, the stat-window and team
pickers, and number formats."""

import pandas as pd
import streamlit as st

import league
from points import data, model


def header(title: str):
    """Title and league context; stops if the league isn't a points league."""
    st.title(title)
    ctx = league.current()
    if not ctx.is_points:
        st.info("This page is for points leagues.")
        st.stop()
    return ctx


def window_picker(ctx, where=st, key: str = "points-window") -> str:
    windows = data.available_windows(ctx.league_id, ctx.version)
    if not windows:
        st.info("No player data yet.")
        st.stop()
    return where.selectbox(
        "Stats from",
        windows,
        format_func=model.WINDOWS.get,
        key=key,
        help="Blended mixes ESPN's projection with season stats as games are played: "
        "season FP/G counts fully from 20 games.",
    )


def my_team_picker(ctx, where=st) -> int:
    """Your own team; the league's commissioner can pick any."""
    team_ids = [int(t) for t in ctx.team_names.index]
    mine, admin = ctx.my_team, ctx.is_commissioner
    if mine is None and not admin:
        st.info("Pick your team on the League settings page to get recommendations for it.")
        st.page_link("views/league_admin.py", label="League settings", icon=":material/tune:")
        st.stop()
    return where.selectbox(
        "Team",
        team_ids if admin else [mine],
        index=team_ids.index(mine) if admin and mine in team_ids else 0,
        format_func=ctx.team_names.get,
        disabled=not admin,
        help=None if admin else "Recommendations are for your own team.",
    )


def team_label(ctx, team_id) -> str:
    if team_id is None or pd.isna(team_id):
        return "Free agent"
    return ctx.team_names.get(int(team_id), str(team_id))


def slots_text(ctx, text) -> str:
    """A player's eligible slots, only those the league's lineup uses (PG, C, UT ...)."""
    used = [slot for slot, _ in ctx.lineup_slots]
    mine = model.slots_of(text)
    return ", ".join(s for s in used if s in mine)


def season_label(ctx) -> str:
    return f"{ctx.season - 1}-{str(ctx.season)[2:]}"


def wins(x) -> str:
    return f"{x:+.2f}"


def pts(x) -> str:
    return f"{x:+.1f}"


def status_text(row) -> str:
    """IR / OUT / day-to-day, or empty for a healthy player."""
    if row.get("is_ir"):
        return "IR"
    return {"OUT": "Out", "DAY_TO_DAY": "Day-to-day"}.get(row.get("injury_status"), "")
