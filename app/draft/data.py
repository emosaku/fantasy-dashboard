"""Cached glue between ESPN's data and the draft engine, for the Draft page.

The Draft page isn't tied to a league: players come from ESPN's league-independent data
(the 400 best by its points draft rank, with ADP, ranks, projections and eligible
slots), the NBA schedule from ESPN's season schedule, both cached for the day, and each
player's games-played history from League Lab's shared history (last season's games
for anyone it hasn't seen). Fantasy points are the projected stats x the setup's point
values.

`format_for` is the one place that picks a format's draft values: points today; a
categories format gets its own builder here and nothing else on the page changes.
"""

import datetime as dt
import random
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from ingest.catalog import POINTS
from ingest.espn_client import fetch_default_pool, fetch_pro_schedule
from ingest.transform import transform_draft_pool, transform_pro_schedule

import queries
from draft import pool as dpool
from draft import recommend, sources, values
from draft.formats import DraftFormat
from draft.simulate import OpponentModel, simulate
from draft.state import Draft, Order

MODEL = OpponentModel()
POOL_SIZE = 400


class FormatNotReady(Exception):
    """The format has no draft values yet; message for people."""


def today() -> str:
    """Today in US Eastern time: ESPN's data is cached for the day."""
    return dt.datetime.now(ZoneInfo("America/New_York")).date().isoformat()


@st.cache_data(ttl=6 * 3600, max_entries=10, show_spinner="Loading ESPN's player pool...")
def espn_pool(season: int, day: str) -> list:
    return fetch_default_pool(season, POOL_SIZE, "STANDARD")


@st.cache_data(ttl=6 * 3600, max_entries=10, show_spinner="Loading the NBA schedule...")
def nba_schedule(season: int, day: str) -> dict:
    return fetch_pro_schedule(season)


def frames(setup: sources.Setup, day: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(draft pool rows, NBA schedule rows) for a setup."""
    now = dt.datetime.now(dt.UTC)
    records = espn_pool(setup.season, day)
    ids = tuple(sorted(int(r["id"]) for r in records))
    history = queries.history_average(ids, setup.season)
    pool = transform_draft_pool(records, setup.season, setup.scoring_rows, history, 0, now)
    pool["history_games"] = pool["history_games"].fillna(pool["last_season_games"])
    schedule = transform_pro_schedule(nba_schedule(setup.season, day), sources.default_matchups(),
                                      {}, 0, setup.season, now)  # fmt: skip
    return pool, schedule


def format_for(setup: sources.Setup, pool: dpool.Pool, schedule: pd.DataFrame,
               risk: str) -> DraftFormat:  # fmt: skip
    if setup.format == POINTS:
        return values.points_format(pool, schedule, setup.starting, len(setup.order.teams),
                                    setup.order.rounds, setup.last_week, risk)  # fmt: skip
    raise FormatNotReady("Categories drafts are next.")


@st.cache_resource(max_entries=20, show_spinner="Loading the draft pool...")
def engine(key: str, day: str, risk: str, _setup: sources.Setup) -> tuple:
    """The pool and the format's values, once per setup, day and risk setting (_setup
    isn't part of the cache key: `key` names it)."""
    raw, schedule = frames(_setup, day)
    pool = dpool.build(raw, dict(_setup.slots), "rank")
    return pool, format_for(_setup, pool, schedule, risk)


@st.cache_data(max_entries=200, show_spinner="Simulating the rest of the draft...")
def advice(key: str, day: str, risk: str, teams: tuple, rounds: int, snake: bool, picks: tuple,
           me: int, runs: int, _setup: sources.Setup) -> recommend.Advice:  # fmt: skip
    pool, fmt = engine(key, day, risk, _setup)
    draft = Draft(Order(teams, rounds, snake), list(picks))
    return recommend.recommend(draft, pool, fmt, MODEL, me, runs=runs)


def bot_pick(draft: Draft, pool: dpool.Pool, fmt: DraftFormat) -> int:
    """A bot's pick for the team on the clock: one simulated manager."""
    k = draft.next_pick
    run = simulate(draft, pool, fmt, MODEL, None, runs=1, seed=random.randrange(10**9),
                   watch=(k,))  # fmt: skip
    return int(pool.ids[run.choices[k][0]])
