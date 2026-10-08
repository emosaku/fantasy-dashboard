"""Saved trades: deals kept from the Trade Analyzer's Waiver wire, Create a trade and
Mock trade tabs, for one team.

  * A saved trade is the whole move from the team's side: the partner (0 = free
    agents, a waiver move), who it sends and gets, and any adds and drops on either
    side -- exactly what Mock trade takes, so it reopens there unchanged.
  * Ranked by what it does for the team with today's data (the page scores each one
    the way Mock trade would), best first.
  * Checked against today's rosters every time it's shown: once a player it sends or
    drops has left the team, a player it gets has left the partner, or a player it adds
    has been picked up, the trade is no longer possible and is removed.

Pure Python: storage lives in saved_store.py, scoring in the page.
"""

import datetime as dt
import hashlib
import json
import math
from dataclasses import asdict, dataclass

FREE_AGENTS = 0
MOVES = ("give", "get", "my_add", "my_drop", "their_add", "their_drop")


def ids_of(players) -> tuple:
    """A move's player ids as a sorted tuple: one id, several, or nobody (None/NaN)."""
    if players is None:
        return ()
    try:
        items = list(players)
    except TypeError:  # a single id
        items = [players]
    out = []
    for p in items:
        if p is None or (isinstance(p, float) and math.isnan(p)):
            continue
        out.append(int(p))
    return tuple(sorted(set(out)))


@dataclass(frozen=True)
class SavedTrade:
    team_id: int  # the team it was saved for
    partner: int  # FREE_AGENTS for a waiver move
    give: tuple = ()  # in a waiver move: the players dropped
    get: tuple = ()  # in a waiver move: the free agents added
    my_add: tuple = ()
    my_drop: tuple = ()
    their_add: tuple = ()
    their_drop: tuple = ()
    source: str = ""  # the tab it was saved from
    saved_at: dt.datetime | None = None
    labels: tuple = ()  # ((player id, name), ...) when saved, for players gone from the data

    @property
    def id(self) -> str:
        """The same move always gets the same id, so saving it twice keeps one."""
        shape = [self.team_id, self.partner, *[list(getattr(self, m)) for m in MOVES]]
        return hashlib.sha256(json.dumps(shape).encode()).hexdigest()[:16]

    @property
    def is_waiver(self) -> bool:
        return self.partner == FREE_AGENTS

    def name(self, pid: int, lookup=None) -> str:
        """A player's name: today's (`lookup(pid)`), else the one saved with the trade."""
        found = lookup(pid) if lookup else None
        return found or dict(self.labels).get(pid) or f"player {pid}"

    def players(self) -> tuple:
        return tuple(p for m in MOVES for p in getattr(self, m))

    def to_dict(self) -> dict:
        out = asdict(self)
        for m in MOVES:
            out[m] = list(out[m])
        out["labels"] = [{"id": p, "name": n} for p, n in self.labels]
        return out

    @classmethod
    def from_dict(cls, data: dict) -> "SavedTrade":
        return make(
            data["team_id"], data["partner"], **{m: data.get(m) or () for m in MOVES},
            source=data.get("source", ""), saved_at=data.get("saved_at"),
            labels={int(x["id"]): x["name"] for x in data.get("labels") or []},
        )  # fmt: skip


def make(team_id, partner, give=(), get=(), my_add=(), my_drop=(), their_add=(), their_drop=(),
         source: str = "", saved_at: dt.datetime | None = None,
         labels: dict | None = None) -> SavedTrade:  # fmt: skip
    """A SavedTrade from the shapes the tabs hold (one id, a list, None or NaN).
    `labels`: player id -> name, kept for the trade's own players."""
    trade = SavedTrade(
        int(team_id), int(partner or FREE_AGENTS), ids_of(give), ids_of(get), ids_of(my_add),
        ids_of(my_drop), ids_of(their_add), ids_of(their_drop), source, saved_at,
    )  # fmt: skip
    kept = tuple((p, str(labels[p])) for p in trade.players() if labels and p in labels)
    return SavedTrade(**{**trade.__dict__, "labels": kept})


def problems(trade: SavedTrade, owner: dict) -> list[tuple[int, str]]:
    """Why a trade is no longer possible: [(player id, where he should be)], where is
    "you", "partner" or "free agents". `owner` maps every player in today's data to his
    team id, or FREE_AGENTS for a free agent.

    Every rostered player is in today's data, so a player who should be on a roster
    but isn't in it has left that roster. A free agent can drop out of the data
    without being picked up (only the best free agents are loaded), so a missing one
    isn't counted as gone: he only is once he's on a roster."""
    found = []

    def on(team, pids, where):
        found.extend((p, where) for p in pids if owner.get(p) != team)

    on(trade.team_id, (*trade.give, *trade.my_drop), "you")
    if trade.is_waiver:
        adds = (*trade.get, *trade.my_add)
    else:
        on(trade.partner, (*trade.get, *trade.their_drop), "partner")
        adds = (*trade.my_add, *trade.their_add)
    found.extend((p, "free agents") for p in adds if owner.get(p, FREE_AGENTS) != FREE_AGENTS)
    return found


def check(trades: list, owner: dict) -> tuple[list, list]:
    """(still possible, [(no longer possible, its problems)])."""
    keep, gone = [], []
    for trade in trades:
        issues = problems(trade, owner)
        if issues:
            gone.append((trade, issues))
        else:
            keep.append(trade)
    return keep, gone


def rank(trades: list, score) -> list[tuple]:
    """[(trade, score)] best first; `score(trade)` returns a number, or None when the
    trade can't be scored with today's data (it goes last)."""
    scored = [(t, score(t)) for t in trades]
    return sorted(scored, key=lambda ts: (ts[1] is None, -(ts[1] or 0.0)))
