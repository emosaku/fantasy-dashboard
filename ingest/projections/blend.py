"""In season: the preseason projection blended with what a player has done so far.

The same regression idea as the model: the preseason projection is a prior worth
PRIOR_MINUTES of play (rates) and PRIOR_GAMES games (minutes per game). Early in the
season the projection dominates; by the All-Star break his own season does.
"""

import pandas as pd

from ingest.projections.games import STATS
from ingest.projections.model import RATE_STATS

PRIOR_MINUTES = 600.0
PRIOR_GAMES = 15.0
SEASON_GAMES = 82


def blend(
    preseason: pd.DataFrame,
    to_date: pd.DataFrame,
    games_left: pd.Series | float,
    prior_minutes: float = PRIOR_MINUTES,
    prior_games: float = PRIOR_GAMES,
) -> pd.DataFrame:
    """Rest-of-season per-game lines.

    preseason: model.project output (per-game lines, GP, MIN). to_date: season_lines
    for the current season (totals so far). games_left: games each player can still
    play -- his team's remaining schedule (a Series by player_id) or one number for all.
    Players with no games yet keep their preseason line; players with games but no
    preseason projection (rookies) use their own line."""
    pre = preseason.set_index("player_id")
    now = to_date.set_index("player_id").reindex(pre.index.union(to_date["player_id"]))
    pre = pre.reindex(now.index)
    played = now["GP"].fillna(0)
    minutes = now["MIN"].fillna(0)

    pre_mpg = pre["MIN"]
    pre_rates = pre[RATE_STATS].div(pre_mpg, axis=0)
    has_pre = pre_mpg.notna() & (pre_mpg > 0)

    rates = (
        pre_rates.mul(prior_minutes)
        .add(now[RATE_STATS].fillna(0))
        .div(minutes + prior_minutes, axis=0)
    )
    own = now[RATE_STATS].div(minutes, axis=0)
    rates.loc[~has_pre] = own.loc[~has_pre]

    mpg = (pre_mpg.fillna(0) * prior_games + minutes) / (prior_games + played)
    mpg.loc[~has_pre] = (minutes / played).loc[~has_pre]

    # share of his remaining games he'll play: his preseason games rate; a player
    # without a projection is assumed to play them all
    share = (pre["GP"] / SEASON_GAMES).clip(upper=1.0).where(has_pre, 1.0)
    left = games_left if isinstance(games_left, int | float) else games_left.reindex(now.index)

    line = rates.mul(mpg, axis=0)
    line["MIN"] = mpg
    line.insert(0, "GP", share * left)
    line = line.loc[(played > 0) | has_pre]
    return line.reset_index()[["player_id", "GP", *STATS]]
