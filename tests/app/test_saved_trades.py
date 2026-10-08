"""Saved trades (app/saved_trades.py) and their League Lab storage (app/saved_store.py)."""

import datetime as dt
import math

import numpy as np

import saved_store
from ingest import registry
from saved_trades import FREE_AGENTS, SavedTrade, check, make, problems, rank
from tests.fixtures.fake_firestore import FakeFirestore

NOW = dt.datetime(2026, 10, 8, tzinfo=dt.UTC)
# Today's data: players 11-13 on team 1 (yours), 21-22 on team 2, 31 on team 3, 90-91 free.
OWNER = {11: 1, 12: 1, 13: 1, 21: 2, 22: 2, 31: 3, 90: FREE_AGENTS, 91: FREE_AGENTS}


def test_a_trade_takes_the_shapes_the_tabs_hold():
    t = make(1, 2, give=[12, 11], get=np.int64(21), my_drop=float("nan"), their_add=None)
    assert (t.give, t.get, t.my_drop, t.their_add) == ((11, 12), (21,), (), ())
    waiver = make(1, None, give=[13], get=[90])
    assert waiver.partner == FREE_AGENTS and waiver.is_waiver


def test_the_same_move_keeps_one_id():
    a = make(1, 2, give=[11, 12], get=[21], source="Mock trade", saved_at=NOW)
    b = make(1, 2, give=[12, 11], get=[21], source="Create a trade")
    assert a.id == b.id  # order, source and time don't make it another trade
    assert a.id != make(1, 2, give=[11], get=[21]).id
    assert a.id != make(1, 3, give=[11, 12], get=[21]).id
    assert SavedTrade.from_dict(a.to_dict()) == a


def test_a_trade_still_possible_has_no_problems():
    trade = make(1, 2, give=[11], get=[21], my_add=[90], my_drop=[12], their_drop=[22],
                 their_add=[91])  # fmt: skip
    assert problems(trade, OWNER) == []
    assert problems(make(1, FREE_AGENTS, give=[13], get=[90]), OWNER) == []


def test_each_roster_change_that_breaks_a_trade_is_named():
    trade = make(1, 2, give=[11], get=[21], my_add=[90], my_drop=[12])
    moved = {**OWNER, 11: 3, 21: 1, 90: 2}  # 11 traded away; 21 now yours; 90 picked up
    del moved[12]  # 12 dropped, now outside the loaded free agents
    assert sorted(problems(trade, moved)) == [
        (11, "you"), (12, "you"), (21, "partner"), (90, "free agents"),
    ]  # fmt: skip


def test_a_free_agent_missing_from_the_data_isnt_counted_as_gone():
    waiver = make(1, FREE_AGENTS, give=[13], get=[95])  # 95: a free agent outside the top 100
    assert problems(waiver, OWNER) == []
    assert problems(waiver, {**OWNER, 95: 3}) == [(95, "free agents")]


def test_check_splits_possible_from_impossible():
    ok = make(1, 2, give=[11], get=[21])
    broken = make(1, 3, give=[11], get=[22])  # 22 is on team 2, not 3
    keep, gone = check([ok, broken], OWNER)
    assert keep == [ok] and gone == [(broken, [(22, "partner")])]


def test_rank_puts_the_best_first_and_unscoreable_last():
    a, b, c = (
        make(1, 2, give=[11], get=[21]),
        make(1, 2, give=[12], get=[21]),
        make(1, 3, give=[13], get=[31]),
    )
    scores = {a.id: 1.5, b.id: None, c.id: 4.0}
    ranked = rank([a, b, c], lambda t: scores[t.id])
    assert [t for t, _ in ranked] == [c, a, b]
    assert ranked[2][1] is None and not math.isnan(ranked[0][1])


def test_saved_trades_are_each_persons_own_and_saved_once():
    db = FakeFirestore()
    trade = make(1, 2, give=[11], get=[21], source="Mock trade", saved_at=NOW)
    saved_store.save(db, 555, "u-ana", trade)
    saved_store.save(db, 555, "u-ana", make(1, 2, give=[11], get=[21], source="Waiver wire"))
    saved_store.save(db, 555, "u-ana", make(4, 2, give=[41], get=[21]))  # another team
    assert [t.id for t in saved_store.load(db, 555, "u-ana", 1)] == [trade.id]
    assert saved_store.load(db, 555, "u-ben", 1) == []
    assert saved_store.load(db, 777, "u-ana", 1) == []
    saved_store.delete(db, 555, "u-ana", trade.id)
    assert saved_store.load(db, 555, "u-ana", 1) == []


def test_deleting_a_league_deletes_its_saved_trades():
    db = FakeFirestore()
    saved_store.save(db, 555, "u-ana", make(1, 2, give=[11], get=[21]))
    saved_store.save(db, 777, "u-ana", make(1, 2, give=[11], get=[21]))
    registry.delete_league(db, 555)
    assert saved_store.load(db, 555, "u-ana", 1) == []
    assert len(saved_store.load(db, 777, "u-ana", 1)) == 1
