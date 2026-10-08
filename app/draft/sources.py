"""A draft's setup: teams, rounds, your draft position, the starting lineup and point
values, entered on the Draft page with ESPN's defaults filled in.

The Draft page isn't tied to any league: it's a mock draft anyone signed in can run at
any time, before a league exists on League Lab or without one at all. Players and the
NBA schedule come from ESPN's league-independent data (draft/data.py).
"""

import hashlib
import json
from dataclasses import dataclass

from ingest.catalog import POINTS

from draft.state import Order

# ESPN's default head-to-head points league.
ESPN_POINTS = (("PTS", 1.0), ("3PM", 1.0), ("FGA", -1.0), ("FGM", 2.0), ("FTA", -1.0),
               ("FTM", 1.0), ("REB", 1.0), ("AST", 2.0), ("STL", 4.0), ("BLK", 4.0),
               ("TO", -2.0))  # fmt: skip
ESPN_SLOTS = (("PG", 1), ("SG", 1), ("SF", 1), ("PF", 1), ("C", 1), ("G", 1), ("F", 1), ("UT", 3))
ESPN_BENCH = 3
REGULAR_WEEKS = 19  # ESPN's default regular season, in matchup weeks
SCORABLE = ("PTS", "3PM", "3PA", "FGM", "FGA", "FTM", "FTA", "REB", "OREB", "DREB", "AST",
            "STL", "BLK", "TO")  # fmt: skip


@dataclass(frozen=True)
class Setup:
    key: str  # names this setup: its cached data and your saved drafts
    season: int
    order: Order
    teams: tuple  # ((team id, name), ...)
    slots: tuple  # ((slot, count), ...), the starting lineup
    bench: int
    scoring: tuple  # ((stat, points), ...)
    my_team: int
    last_week: int = REGULAR_WEEKS
    format: str = POINTS

    @property
    def names(self) -> dict:
        return dict(self.teams)

    @property
    def scoring_rows(self) -> list[dict]:
        return [{"stat": s, "points": float(p)} for s, p in self.scoring]

    @property
    def starting(self) -> int:
        return int(sum(c for _, c in self.slots))


def make(season: int, teams: int, rounds: int, position: int, slots=ESPN_SLOTS,
         bench: int = ESPN_BENCH, scoring=ESPN_POINTS) -> Setup:  # fmt: skip
    """Teams 1..n in draft order (a snake), you at `position`. Slots or stats worth
    nothing are left out; the key changes with anything that changes the draft."""
    slots = tuple((str(s), int(c)) for s, c in slots if int(c) > 0)
    scoring = tuple((str(s), float(p)) for s, p in scoring if float(p) != 0)
    shape = json.dumps([season, teams, rounds, position, slots, bench, scoring])
    return Setup(
        key=hashlib.sha256(shape.encode()).hexdigest()[:12],
        season=season,
        order=Order(tuple(range(1, teams + 1)), int(rounds)),
        teams=tuple((t, "You" if t == position else f"Team {t}") for t in range(1, teams + 1)),
        slots=slots,
        bench=int(bench),
        scoring=scoring,
        my_team=int(position),
    )


def default_matchups(weeks: int = 30) -> dict:
    """Matchup week n = ESPN's base week n (Monday to Sunday from opening night)."""
    return {str(n): [n] for n in range(1, weeks + 1)}
