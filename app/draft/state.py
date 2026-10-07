"""A snake draft's state: who picks when, every pick so far, each team's roster.

Pure Python, stored as a plain dict (Firestore for a live draft, the session for a
mock), so it knows nothing about how players are valued.

  * Order: the round-1 order and the number of rounds. In a snake the order
    reverses every round. Pick numbers are overall and 1-based, like ESPN's.
  * Draft: the picks so far as (team, player) in pick order. A pick can be recorded
    for a team other than the one the order expects (a traded pick); future picks
    still follow the order.
  * Entering picks: `matches` ranks players for what was typed (a few letters of a
    first or last name is enough, typos tolerated), and `parse_paste` finds players,
    in order, in text copied from a draft room.
"""

import difflib
import re
import unicodedata
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Order:
    teams: tuple  # round-1 pick order, team ids
    rounds: int
    snake: bool = True

    @property
    def total(self) -> int:
        return len(self.teams) * self.rounds

    def owner(self, overall: int) -> int:
        """The team the order gives pick `overall` (1-based)."""
        n = len(self.teams)
        rnd, i = divmod(overall - 1, n)
        reverse = self.snake and rnd % 2 == 1
        return self.teams[n - 1 - i if reverse else i]

    def round_of(self, overall: int) -> tuple[int, int]:
        """(round, pick within the round), both 1-based."""
        rnd, i = divmod(overall - 1, len(self.teams))
        return rnd + 1, i + 1

    def picks_of(self, team: int) -> list[int]:
        return [k for k in range(1, self.total + 1) if self.owner(k) == team]


class DraftError(Exception):
    """A pick that can't be made; the message is for people."""


@dataclass
class Draft:
    order: Order
    picks: list = field(default_factory=list)  # [(team_id, player_id)] in pick order

    @property
    def next_pick(self) -> int:
        return len(self.picks) + 1

    @property
    def done(self) -> bool:
        return len(self.picks) >= self.order.total

    @property
    def on_clock(self) -> int | None:
        return None if self.done else self.order.owner(self.next_pick)

    def taken(self) -> set:
        return {player for _, player in self.picks}

    def add(self, player: int, team: int | None = None) -> None:
        if self.done:
            raise DraftError("The draft is over.")
        if player in self.taken():
            raise DraftError("That player has already been drafted.")
        self.picks.append((int(self.on_clock if team is None else team), int(player)))

    def undo(self) -> tuple | None:
        return self.picks.pop() if self.picks else None

    def rosters(self) -> dict[int, list[int]]:
        """Every team's picks so far, in pick order (teams with none included)."""
        out = {int(t): [] for t in self.order.teams}
        for team, player in self.picks:
            out.setdefault(int(team), []).append(int(player))
        return out

    def next_pick_of(self, team: int, after: int | None = None) -> int | None:
        """The first pick from `after` (default: the next pick) that the order gives
        `team`, or None if it has no more."""
        start = self.next_pick if after is None else after
        for k in range(start, self.order.total + 1):
            if self.order.owner(k) == team:
                return k
        return None

    def to_dict(self) -> dict:
        return {
            "teams": list(self.order.teams),
            "rounds": self.order.rounds,
            "snake": self.order.snake,
            "picks": [{"team": t, "player": p} for t, p in self.picks],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Draft":
        order = Order(tuple(int(t) for t in data["teams"]), int(data["rounds"]),
                      bool(data.get("snake", True)))  # fmt: skip
        return cls(order, [(int(p["team"]), int(p["player"])) for p in data.get("picks", [])])


# --- Entering picks -----------------------------------------------------------------------


CLOSE_SPELLING = 0.75  # difflib ratio for a typo to still match


def normalize(text: str) -> str:
    """Lower case, accents and punctuation gone: "Nikola Jokić" -> "nikola jokic"."""
    plain = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", "", plain.lower().replace("-", " ")).strip()


def matches(query: str, names: dict, limit: int = 5) -> list:
    """Players for what was typed, best first: an exact name, then names whose first
    or last name starts with it, then names containing it, then close spellings.
    `names` maps player id -> name, in the order ties should break (best first)."""
    q = normalize(query)
    if not q:
        return []
    exact, starts, contains = [], [], []
    for pid, name in names.items():
        n = normalize(name)
        if n == q:
            exact.append(pid)
        elif n.startswith(q) or any(part.startswith(q) for part in n.split()):
            starts.append(pid)
        elif q in n:
            contains.append(pid)
    found = exact + starts + contains
    if not found:
        # Close spellings, against the whole name and each part ("jokci" ~ "jokic").
        close = []
        for pid, name in names.items():
            if pid in found:
                continue
            n = normalize(name)
            score = max(difflib.SequenceMatcher(None, q, part).ratio() for part in [n, *n.split()])
            if score >= CLOSE_SPELLING:
                close.append((-score, len(close), pid))
        found += [pid for _, _, pid in sorted(close)]
    return found[:limit]


def parse_paste(text: str, names: dict) -> list:
    """Players named in pasted text, in the order they appear, each once. A line can
    hold several names; the longest name found at each spot wins (so "Jalen Johnson"
    isn't read as "Jalen")."""
    by_name = sorted(((normalize(n), pid) for pid, n in names.items()), key=lambda x: -len(x[0]))
    found, seen = [], set()
    for line in (text or "").splitlines():
        rest = f" {normalize(line)} "
        hits = []
        for name, pid in by_name:
            if not name:
                continue
            at = rest.find(f" {name} ")
            if at >= 0 and pid not in seen:
                hits.append((at, pid))
                rest = rest[:at] + " " * (len(name) + 2) + rest[at + len(name) + 2 :]
        for _, pid in sorted(hits):
            if pid not in seen:
                found.append(pid)
                seen.add(pid)
    return found


def merge_official(draft: Draft, official: list) -> Draft:
    """The draft with ESPN's picks [(overall, team, player)] -- ESPN numbers them 1, 2,
    3 ... -- followed by the picks entered by hand after ESPN's last one (unless ESPN
    already has that player). ESPN is the record: an entered pick it contradicts is
    replaced."""
    if not official:
        return Draft(draft.order, list(draft.picks))
    ordered = sorted((int(k), int(t), int(p)) for k, t, p in official)
    picks = [(t, p) for _, t, p in ordered]
    have = {p for _, p in picks}
    picks += [(t, p) for t, p in draft.picks[len(picks) :] if p not in have]
    return Draft(draft.order, picks[: draft.order.total])
