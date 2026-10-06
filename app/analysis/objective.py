"""The scoreboard every move is judged by.

E = how many categories a team would win if it played every other team, from the
team totals; a tie counts half. With N teams and K categories the most is K x (N - 1).
A category the team punts is left out of its own E, so the objective matches its strategy.
"""

import numpy as np
import pandas as pd


def category_wins(rows: np.ndarray, others: np.ndarray) -> np.ndarray:
    """Per-category wins of each row against every row of `others`, ties half.

    rows: (..., K). others: (M, K). Returns (..., K).
    """
    r = rows[..., None, :]
    return (r > others).sum(axis=-2) + 0.5 * (r == others).sum(axis=-2)


def head_to_head(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Per-category result of a vs b, elementwise: 1 win, 0.5 tie, 0 loss."""
    return (a > b) + 0.5 * (a == b)


def per_category_wins(totals: pd.DataFrame, team_id: int) -> pd.Series:
    me = totals.loc[team_id].to_numpy()
    others = totals.drop(team_id).to_numpy()
    return pd.Series(category_wins(me, others), index=totals.columns)


def expected_category_wins(totals: pd.DataFrame, team_id: int, punts=()) -> float:
    """E for one team: categories won against every other team, punts excluded."""
    return float(per_category_wins(totals, team_id).drop(list(punts)).sum())


def matchup_record(totals: pd.DataFrame, team_id: int) -> tuple[int, int, int]:
    """All-play matchup record: against each opponent, a win means taking more of the
    categories than it does -- the way a real Most Categories week is decided.
    Every category counts here, punted or not, because a real matchup counts them."""
    me = totals.loc[team_id].to_numpy()
    wins = losses = ties = 0
    for row in totals.drop(team_id).to_numpy():
        won, lost = int((me > row).sum()), int((me < row).sum())
        if won > lost:
            wins += 1
        elif won < lost:
            losses += 1
        else:
            ties += 1
    return wins, losses, ties
