"""The API's glue to the analysis engine: the same pure functions the Streamlit pages
reach through analyzer.py and points/data.py, called without Streamlit.

No math lives here. Each function takes plain frames (the m_* tables and raw tables
a league reads) and calls app/analysis/ (categories leagues) or app/points/ (points
leagues) exactly as the pages do; where a page adds a small step of its own (which
stat window, which team's weights), it's repeated here with a pointer to the page.
"""

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd

from analysis import trades as cat_trades
from analysis.explain import explain, pitch_text
from analysis.objective import expected_category_wins, matchup_record
from analysis.pool import empty_slot_z, player_matrix, team_totals
from analysis.projection import InjuryRules, per_game_lines, project_season
from analysis.rankings import player_rankings
from analysis.waivers import rank_waiver_moves
from analysis.weights import compute_weights, generic_values, punts
from categories import Category
from points import explain as pts_explain
from points import model
from points import trades as pts_trades
from trade import wide_lines

# analyzer.STAT_WINDOWS and points.model.WINDOWS: the windows, in the pages' order.
WINDOWS = ["blended", "projected", "season", "last_7", "last_15", "last_30"]
DEFAULT_DELTA = 1.0  # Trade Analyzer's "swing size" default
FINDER_TOP = 200  # rows kept per team in the finder cache
INFO = ["player_name", "position", "pro_team", "team_id", "lineup_slot", "injury_status",
        "expected_return_date", "eligible_slots", "is_free_agent", "is_ir"]  # fmt: skip


# --- Categories leagues (analyzer.py) -------------------------------------------------


def cat_windows(player_z: pd.DataFrame) -> list[str]:
    have = set(player_z["stat_window"])
    return [w for w in WINDOWS if w in have]


def cat_league(player_z: pd.DataFrame, window: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(players, team totals) for one stat window: analyzer.league."""
    players = player_matrix(player_z.loc[player_z["stat_window"] == window])
    return players, team_totals(players)


def cat_weights(totals: pd.DataFrame, me: int, delta: float = DEFAULT_DELTA,
                overrides: dict | None = None) -> dict:  # fmt: skip
    """Every team's weights; only `me` gets the overrides: analyzer.weights_by_team."""
    return {
        t: compute_weights(totals, t, delta, (overrides or None) if t == me else None)
        for t in totals.index
    }


def cat_empty_slot(player_z: pd.DataFrame, window: str) -> pd.Series:
    """analyzer.empty_slot: blended averages season and projected."""
    raw = ["season", "projected"] if window == "blended" else [window]
    found = [empty_slot_z(player_z.loc[player_z["stat_window"] == w]) for w in raw
             if (player_z["stat_window"] == w).any()]  # fmt: skip
    return pd.concat(found, axis=1).mean(axis=1) if found else pd.Series(dtype=float)


def cat_finder(players, totals, me: int, weights: dict, top: int = FINDER_TOP) -> pd.DataFrame:
    return cat_trades.find_trades(players, totals, me, weights, top=top)


def cat_waivers(players, totals, me: int, weights: dict, top: int = 10) -> pd.DataFrame:
    return rank_waiver_moves(players, totals, me, weights[me], top=top)


def cat_deltas(row, columns: list[str], prefix: str = "dE_") -> dict:
    """A deal row's change in expected category wins per category (the page's helper)."""
    return {c: float(row[f"{prefix}{c}"]) for c in columns}


@dataclass
class CatMock:
    my_delta_e: float
    their_delta_e: float | None
    my_categories: dict
    their_categories: dict | None
    my_e_before: float
    my_e_after: float
    my_record_before: tuple
    my_record_after: tuple
    lopsided: bool
    reason: str
    pitch: str | None


def cat_mock(players, totals, player_z, window: str, me: int, them: int | None, weights: dict,
             give=(), get=(), my_drop=(), their_drop=(), my_add=(),
             their_add=()) -> CatMock:  # fmt: skip
    """The Trade Analyzer's mock trade: analysis.trades.simulate_trade with each side's
    punts and the window's empty-slot value, then the same before/after figures the
    page shows (expected category wins, matchup record)."""
    punts_me = punts(weights[me])
    punts_them = () if them is None else punts(weights[them])
    after, mine, theirs = cat_trades.simulate_trade(
        players, totals, me, them, list(give), list(get), list(my_drop), list(their_drop),
        list(my_add), list(their_add), punts_me, punts_them, cat_empty_slot(player_z, window),
    )  # fmt: skip
    generic = generic_values(players)
    gen_give = float(sum(generic[p] for p in give))
    gen_get = float(sum(generic[p] for p in get))
    return CatMock(
        my_delta_e=mine.delta_e,
        their_delta_e=None if theirs is None else theirs.delta_e,
        my_categories={k: float(v) for k, v in mine.cat_delta.items()},
        their_categories=None if theirs is None
        else {k: float(v) for k, v in theirs.cat_delta.items()},
        my_e_before=float(expected_category_wins(totals, me, punts_me)),
        my_e_after=float(expected_category_wins(after, me, punts_me)),
        my_record_before=tuple(int(x) for x in matchup_record(totals, me)),
        my_record_after=tuple(int(x) for x in matchup_record(after, me)),
        lopsided=bool(them is not None and abs(gen_give - gen_get) > cat_trades.LOPSIDED_GAP),
        reason=explain(mine.cat_delta),
        pitch=None if theirs is None else pitch_text(theirs.cat_delta),
    )  # fmt: skip


def cat_projected_finish(player_pool, all_play, cats: list[Category], current_week: int,
                         last_week: int, as_of: dt.date, team_ids,
                         each_category: bool) -> pd.DataFrame:  # fmt: skip
    """Power Rankings' projected finish with the default injury rules."""
    return project_season(per_game_lines(player_pool), all_play, cats, current_week, last_week,
                          as_of, InjuryRules(), team_ids, each_category)  # fmt: skip


def cat_rankings(player_z: pd.DataFrame, window: str) -> pd.DataFrame:
    return player_rankings(player_z.loc[player_z["stat_window"] == window])


def verdict(my_delta: float, their_delta: float | None, lopsided: bool) -> str:
    """A trade's verdict word, the same rule as points.trades.status (and the finder's
    win-win filter): good for me and not worse for them (or a free-agent move) =
    win-win; good for me but worse for them or lopsided = they say no; otherwise it
    costs you."""
    fair = (their_delta is None or their_delta >= -1e-9) and not lopsided
    if my_delta > 1e-9:
        return cat_trades.WIN_WIN if fair else cat_trades.THEY_SAY_NO
    return cat_trades.COSTS_YOU if fair else cat_trades.THEY_SAY_NO


# --- Points leagues (points/data.py) --------------------------------------------------


def pts_windows(player_points: pd.DataFrame) -> list[str]:
    have = set(player_points["stat_window"])
    if not have:
        return []
    blended = {"season", "projected"} & have
    return [w for w in model.WINDOWS if w in have or (w == "blended" and blended)]


def pts_players(player_pool: pd.DataFrame, player_points: pd.DataFrame,
                window: str) -> pd.DataFrame:  # fmt: skip
    """points/data.players: one row per pool player with FP/G in `window`."""
    info = player_pool.drop_duplicates("player_id").set_index("player_id")
    info = info[[c for c in INFO if c in info]]
    wide = model.fp_wide(player_points)
    out = info.join(wide, how="left")
    out["fpg"] = model.fp_per_game(out, window) if not wide.empty else 0.0
    out["team_id"] = out["team_id"].astype("float64")
    return out


def pts_stat_lines(player_pool: pd.DataFrame, window: str) -> pd.DataFrame:
    """points/data.stat_lines."""
    if window == "blended":
        has_season = set(player_pool.loc[player_pool["stat_window"] == "season", "player_id"])
        rows = player_pool.loc[
            (player_pool["stat_window"] == "season")
            | ((player_pool["stat_window"] == "projected")
               & ~player_pool["player_id"].isin(has_season))
        ]  # fmt: skip
    else:
        rows = player_pool.loc[player_pool["stat_window"] == window]
    return wide_lines(rows).set_index("player_id")


def pts_setup(players, schedule, slots: dict, bench: int, current_week: int, last_week: int,
              day: dt.date, matchup_scores: pd.DataFrame) -> pts_trades.Setup:  # fmt: skip
    """points/data.setup: the engine for one league and window, as of `day`."""
    results = model.played_results(matchup_scores, current_week)
    return pts_trades.build(players, schedule, slots, bench, current_week, last_week, day,
                            results)  # fmt: skip


def share_of_week_left(schedule: pd.DataFrame, week: int, day: dt.date) -> float:
    """points/data.share_of_week_left."""
    days = schedule.loc[schedule["matchup_period"] == week, "game_date"]
    days = pd.to_datetime(days).dt.date.unique()
    if not len(days):
        return 0.0
    return sum(d >= day for d in days) / len(days)


def pts_projected_finish(setup, matchup_scores, schedule, current_week: int, last_week: int,
                         day: dt.date) -> pd.DataFrame:  # fmt: skip
    """Points Power Rankings' projected finish: projected weekly points (mu), expected
    weekly wins, and the projected final record."""
    mu = setup.team_mu(full=True)
    finish = model.projected_finish(matchup_scores, mu, setup.sigma, current_week, last_week,
                                    share_of_week_left(schedule, current_week, day))  # fmt: skip
    finish["mu"] = mu.reindex(finish.index)
    finish["expected_wins"] = model.expected_wins(mu, setup.sigma).reindex(finish.index)
    return finish


def pts_deal_text(players: pd.DataFrame, deal) -> dict:
    return {"reason": pts_explain.why(players, deal), "pitch": pts_explain.pitch(players, deal)}


# --- Shared --------------------------------------------------------------------------


def records(frame: pd.DataFrame | None, index: str | None = None) -> list[dict]:
    """A frame as JSON-ready rows: NaN and NaT become None, numpy and dates plain."""
    if frame is None or frame.empty:
        return []
    out = frame.reset_index() if index else frame
    if index and index not in out and "index" in out:
        out = out.rename(columns={"index": index})
    return [{k: plain(v) for k, v in row.items()} for row in out.to_dict("records")]


def plain(value):
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, np.ndarray):
        return [plain(v) for v in value.tolist()]
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if value is None:
        return None
    if isinstance(value, float | np.floating):
        return None if np.isnan(value) else float(value)
    if isinstance(value, bool | np.bool_):
        return bool(value)
    if isinstance(value, int | np.integer):
        return int(value)
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.isoformat()
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value
