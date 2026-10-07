"""The full daily lineup simulation for points leagues. Pure Python, no Streamlit.

Each day of each week, a team starts the best legal lineup from its players with a
game that day: every starting slot (PG, SG, G, UT ...) holds one player eligible for
it. Since a player scores the same in any slot, the best lineup is found greedily:
take players best first, keeping each one if the chosen set can still be seated
(checked with an augmenting-path matching). For seating problems like this -- a
transversal matroid -- greedy by value is exactly optimal.

Players with no points to add (FP/G <= 0) sit, as a manager would sit them.
"""

from collections.abc import Iterable


def _seat(player, slots_of, seats, holder, seen) -> bool:
    """Try to give `player` a seat, moving others along augmenting paths."""
    for seat, slot in enumerate(seats):
        if slot not in slots_of[player] or seat in seen:
            continue
        seen.add(seat)
        if holder[seat] is None or _seat(holder[seat], slots_of, seats, holder, seen):
            holder[seat] = player
            return True
    return False


def best_lineup(players: Iterable, fpg: dict, slots_of: dict, slot_counts: dict) -> list:
    """The players who start: the highest-scoring set that fits the slots."""
    seats = [slot for slot, count in slot_counts.items() for _ in range(int(count))]
    holder = [None] * len(seats)
    started = []
    for player in sorted(players, key=lambda p: (-fpg[p], str(p))):
        if fpg[player] <= 0 or len(started) == len(seats):
            break
        trial = list(holder)
        if _seat(player, slots_of, seats, trial, set()):
            holder = trial
            started.append(player)
    return started


def simulate_weeks(roster: list, fpg: dict, slots_of: dict, team_of: dict, back: dict,
                   slot_counts: dict, days: list) -> dict:  # fmt: skip
    """Projected points per week from the real schedule.

    days: [(week, frozenset of NBA teams playing that day)], one entry per game day.
    For each player: fpg[p] his FP/G, slots_of[p] his eligible slots, team_of[p] his
    NBA team, back[p] the first week he counts (injuries).

    Returns {"weeks": {week: points}, "starts": {player: games started}}.
    """
    weeks: dict = {}
    starts = dict.fromkeys(roster, 0)
    memo: dict = {}
    for week, playing in days:
        available = tuple(
            sorted(p for p in roster if team_of.get(p) in playing and back.get(p, 0) <= week)
        )
        if available not in memo:
            memo[available] = best_lineup(available, fpg, slots_of, slot_counts)
        lineup = memo[available]
        weeks[week] = weeks.get(week, 0.0) + sum(fpg[p] for p in lineup)
        for p in lineup:
            starts[p] += 1
    return {"weeks": weeks, "starts": starts}
