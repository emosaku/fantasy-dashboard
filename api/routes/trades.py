"""The Trades page: the trade finder feed, the waiver wire, a mock trade's verdict,
and saved trades. All the math is the engine's (app/analysis, app/points); these
endpoints pick the team and window, call it, and put names and verdicts on the rows.

`team` defaults to the caller's own team; only the league's commissioner may ask for
another team's recommendations (as in the Streamlit Trade Analyzer)."""

import datetime as dt
import json

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

import saved_trades
from analysis import trades as cat_trades
from api import engine
from api.auth import User
from api.context import current_user, store
from api.routes.leagues import body, data
from api.services import LeagueData
from points import trades as pts_trades

router = APIRouter(prefix="/leagues/{league_id}")
TIERS = {"Lock", "Swing", "Punt"}


def _overrides(text: str | None, d: LeagueData) -> dict | None:
    """Tier overrides as JSON: {"BLK": "Punt", ...} (categories leagues only)."""
    if not text:
        return None
    try:
        found = json.loads(text)
    except json.JSONDecodeError:
        raise HTTPException(422, 'overrides must be JSON, like {"BLK": "Punt"}.') from None
    cats = set(d.columns())
    if not isinstance(found, dict) or any(k not in cats or v not in TIERS
                                          for k, v in found.items()):  # fmt: skip
        raise HTTPException(422, "overrides map this league's categories to Lock, Swing or Punt.")
    return found


@router.get("/trade-finder")
def trade_finder(team: int | None = None, window: str | None = None,
                 delta: float = Query(engine.DEFAULT_DELTA, ge=0.25, le=3.0),
                 overrides: str | None = None, d: LeagueData = Depends(data)):  # fmt: skip
    """Win-win trades for my team, best first: each names both teams, what each side
    gains, a verdict and a plain-language reason (and, points leagues, a pitch)."""
    me = d.ctx.team_for(team)
    window = d.window(window)
    tiers = None if d.ctx.is_points else _overrides(overrides, d)
    deals = d.finder(me, window, delta, tiers)
    return body(d, team_id=me, window=window, deals=deals)


@router.get("/waiver-wire")
def waiver_wire(team: int | None = None, window: str | None = None,
                d: LeagueData = Depends(data)):  # fmt: skip
    """The best add (and drop) moves for my team."""
    me = d.ctx.team_for(team)
    window = d.window(window)
    if d.ctx.is_points:
        setup = d.setup(window)
        moves = d.pts_waivers(window, me)
        names = setup.players["player_name"]
        out = [{"add_id": int(m["add_id"]), "add": names.get(m["add_id"]),
                "drop_id": None if not cat_trades.present(m["drop_id"]) else int(m["drop_id"]),
                "drop": names.get(m["drop_id"]) if cat_trades.present(m["drop_id"]) else None,
                "my_change": float(m["dE"]), "my_points_change": float(m["dmu"]),
                "change_unit": "expected wins a week"} for _, m in moves.iterrows()]  # fmt: skip
        return body(d, team_id=me, window=window, moves=out)
    players, totals = d.cat_league(window)
    if me not in totals.index:
        return body(d, team_id=me, window=window, moves=[])
    weights = engine.cat_weights(totals, me)
    moves = engine.cat_waivers(players, totals, me, weights)
    cols = d.columns()
    out = []
    for _, m in moves.iterrows():
        cats = engine.cat_deltas(m, cols)
        drop = m.get("drop_id")
        out.append({"add_id": int(m["add_id"]), "add": m.get("add_name"),
                    "drop_id": int(drop) if cat_trades.present(drop) else None,
                    "drop": m.get("drop_name") or None, "my_change": float(m["dE"]),
                    "change_unit": "expected category wins a week", "categories": cats,
                    "reason": engine.explain(cats)})  # fmt: skip
    return body(d, team_id=me, window=window, moves=out)


class Move(BaseModel):
    team: int | None = None
    partner: int | None = None  # None: a free-agent move
    give: list[int] = []
    get: list[int] = []
    my_add: list[int] = []
    my_drop: list[int] = []
    their_add: list[int] = []
    their_drop: list[int] = []
    window: str | None = None


def _check(move: Move, me: int, d: LeagueData, team_of) -> None:
    """Every player must be where the move says: mine, theirs or a free agent."""
    if move.partner is not None and (move.partner == me or move.partner not in d.ctx.teams):
        raise HTTPException(422, "Pick another team in this league as the partner.")
    if move.partner is None and (move.get or move.their_add or move.their_drop):
        raise HTTPException(422, "A free-agent move has no partner side: use my_add / my_drop.")
    if not any([move.give, move.get, move.my_add, move.my_drop]):
        raise HTTPException(422, "Pick players for the move.")
    where = {**{p: me for p in move.give + move.my_drop},
             **{p: move.partner for p in move.get + move.their_drop},
             **{p: None for p in move.my_add + move.their_add}}  # fmt: skip
    for pid, owner in where.items():
        if pid not in team_of:
            raise HTTPException(422, f"Player {pid} isn't in this league's pool.")
        if team_of[pid] != owner:
            raise HTTPException(422, f"Player {pid} isn't where this move says he is.")


@router.post("/trades/analyze")
def analyze(move: Move, d: LeagueData = Depends(data)):
    """A mock trade or free-agent move: the verdict first, then the numbers behind it
    (the show-your-work block)."""
    me = d.ctx.team_for(move.team)
    window = d.window(move.window)
    if d.ctx.is_points:
        setup = d.setup(window)
        team_of = {int(p): (None if pd.isna(t) else int(t))
                   for p, t in setup.players["team_id"].items()}  # fmt: skip
        _check(move, me, d, team_of)
        result = pts_trades.mock(setup, me, move.partner, tuple(move.give), tuple(move.get),
                                 tuple(move.my_add), tuple(move.my_drop), tuple(move.their_add),
                                 tuple(move.their_drop))  # fmt: skip
        mine = float(result["dE"][me])
        theirs = None if move.partner is None else float(result["dE"][move.partner])
        value = setup.players["season_value"]
        # The finder's own rule (points.trades.score_pair): what I give vs what I get.
        # It only checks my side; see docs/reactDocs/phase1-api.md (open question).
        lopsided = move.partner is not None and pts_trades.lopsided(
            float(value.reindex(move.give).sum()), float(value.reindex(move.get).sum())
        )
        return body(d, team_id=me, window=window,
                    verdict=engine.verdict(mine, theirs, bool(lopsided)),
                    my_change=mine, their_change=theirs, change_unit="expected wins a week",
                    work={"points_before": engine.plain(result["mu_before"].to_dict()),
                          "points_after": engine.plain(result["mu_after"].to_dict()),
                          "wins_before": engine.plain(result["e_before"].to_dict()),
                          "wins_after": engine.plain(result["e_after"].to_dict()),
                          "rosters_after": engine.plain(result["rosters"])},
                    lopsided=bool(lopsided))  # fmt: skip
    players, totals = d.cat_league(window)
    if me not in totals.index:
        raise HTTPException(409, "This team has no players with stats in this window.")
    team_of = {int(p): (None if pd.isna(t) else int(t)) for p, t in players["team_id"].items()}
    _check(move, me, d, team_of)
    weights = engine.cat_weights(totals, me)
    result = engine.cat_mock(players, totals, d.table("m_player_z"), window, me, move.partner,
                             weights, move.give, move.get, move.my_drop, move.their_drop,
                             move.my_add, move.their_add)  # fmt: skip
    return body(d, team_id=me, window=window,
                verdict=engine.verdict(result.my_delta_e, result.their_delta_e,
                                       result.lopsided),
                my_change=result.my_delta_e, their_change=result.their_delta_e,
                change_unit="expected category wins a week", reason=result.reason,
                pitch=result.pitch, lopsided=result.lopsided,
                work={"my_categories": result.my_categories,
                      "their_categories": result.their_categories,
                      "my_expected_wins": [result.my_e_before, result.my_e_after],
                      "my_matchup_record": [list(result.my_record_before),
                                            list(result.my_record_after)]})  # fmt: skip


class SaveIn(Move):
    source: str = "api"


@router.get("/saved-trades")
def saved(team: int | None = None, d: LeagueData = Depends(data),
          user: User = Depends(current_user), store=Depends(store)):  # fmt: skip
    me = d.ctx.team_for(team)
    found = store.saved_load(d.ctx.league_id, user.uid, me)
    return body(d, team_id=me, trades=[{"id": t.id, **engine.plain(t.to_dict())}
                                       for t in found])  # fmt: skip


@router.post("/saved-trades", status_code=201)
def save(move: SaveIn, d: LeagueData = Depends(data), user: User = Depends(current_user),
         store=Depends(store)):  # fmt: skip
    me = d.ctx.team_for(move.team)
    names = d.names().to_dict()
    trade = saved_trades.make(me, move.partner, move.give, move.get, move.my_add,
                              move.my_drop, move.their_add, move.their_drop, source=move.source,
                              saved_at=dt.datetime.now(dt.UTC), labels=names)  # fmt: skip
    store.saved_save(d.ctx.league_id, user.uid, trade)
    return {"id": trade.id}


@router.delete("/saved-trades/{trade_id}", status_code=204)
def unsave(trade_id: str, d: LeagueData = Depends(data), user: User = Depends(current_user),
           store=Depends(store)):  # fmt: skip
    store.saved_delete(d.ctx.league_id, user.uid, trade_id)
