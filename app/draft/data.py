"""Cached glue between the league's data and the draft engine, for the Draft page.

`format_for` is the one place that picks a league format's draft values: points today;
a categories league gets its own builder here (values.categories_format) and nothing
else on the page changes.
"""

import random

import streamlit as st

import queries
from draft import pool as dpool
from draft import recommend, values
from draft.formats import DraftFormat
from draft.simulate import OpponentModel, simulate
from draft.state import Draft, Order

MODEL = OpponentModel()


class FormatNotReady(Exception):
    """The league's format has no draft values yet; message for people."""


def order_for(ctx) -> Order:
    """The draft order from ESPN's settings; teams by id and every roster spot but IR
    when ESPN hasn't set one yet."""
    settings = ctx.doc.get("draft") or {}
    teams = settings.get("pick_order") or [int(t) for t in ctx.team_names.index]
    rounds = settings.get("rounds") or (
        sum(c for _, c in ctx.lineup_slots) + int(ctx.doc.get("bench_slots") or 0)
    )
    return Order(tuple(int(t) for t in teams), int(rounds), settings.get("type") != "LINEAR")


def format_for(ctx, pool: dpool.Pool, risk: str) -> DraftFormat:
    if ctx.is_points:
        order = order_for(ctx)
        return values.points_format(pool, queries.pro_schedule(ctx.league_id, ctx.version),
                                    sum(c for _, c in ctx.lineup_slots), len(order.teams),
                                    order.rounds, ctx.last_week, risk)  # fmt: skip
    raise FormatNotReady("The Draft Tool runs points leagues for now; categories drafts are next.")


@st.cache_resource(max_entries=20, show_spinner="Loading the draft pool...")
def engine(league_id: int, version: str, risk: str, _ctx) -> tuple[dpool.Pool, DraftFormat]:
    """The pool and the league format's values (one per league, data version and risk
    setting; _ctx isn't part of the cache key)."""
    rank = "rank" if _ctx.is_points else "rank_roto"
    pool = dpool.build(queries.draft_pool(league_id, version), dict(_ctx.lineup_slots), rank)
    return pool, format_for(_ctx, pool, risk)


@st.cache_data(max_entries=200, show_spinner="Simulating the rest of the draft...")
def advice(league_id: int, version: str, risk: str, teams: tuple, rounds: int, snake: bool,
           picks: tuple, me: int, runs: int, _ctx) -> recommend.Advice:  # fmt: skip
    pool, fmt = engine(league_id, version, risk, _ctx)
    draft = Draft(Order(teams, rounds, snake), list(picks))
    return recommend.recommend(draft, pool, fmt, MODEL, me, runs=runs)


def bot_pick(draft: Draft, pool: dpool.Pool, fmt: DraftFormat) -> int:
    """A mock-draft bot's pick for the team on the clock: one simulated manager."""
    k = draft.next_pick
    run = simulate(draft, pool, fmt, MODEL, None, runs=1, seed=random.randrange(10**9),
                   watch=(k,))  # fmt: skip
    return int(pool.ids[run.choices[k][0]])


def official_picks(league_id: int, version: str) -> list:
    """ESPN's picks from the last data load: [(overall, team, player)]."""
    picks = queries.draft_picks(league_id, version)
    if picks.empty:
        return []
    rows = picks.sort_values("overall")
    return list(zip(rows["overall"], rows["team_id"], rows["player_id"], strict=True))


def espn_now(league_id: int, season: int) -> list:
    """ESPN's picks right now, read straight from ESPN (public leagues only)."""
    from ingest.espn_client import fetch_views

    detail = fetch_views(league_id, season, ["mDraftDetail"]).get("draftDetail") or {}
    return [
        (p["overallPickNumber"], p["teamId"], p["playerId"])
        for p in detail.get("picks") or []
        if p.get("playerId", -1) > 0
    ]
