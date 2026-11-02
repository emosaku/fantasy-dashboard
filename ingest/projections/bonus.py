"""Projected bonus stats (docs/whopDocs/bonus-stats.md): each player's expected
double-doubles, triple-doubles, quadruple-doubles, personal fouls and foul-outs per
game.

A bonus is a share of games (a double-double in 60% of them), and players repeat their
share closely from year to year, so the projection is his own recent rate: this
season's games count 3x, last season's 1x, the season before 0.5x, pulled toward the
league's rate by PRIOR_GAMES games of it (so a player with few games, like a rookie,
starts near the league's rate). Tested on 2024-25 and 2025-26: about 0.045 mean error
in double-double share, as good as repeating last season before it starts and 6%
better once 10-25 games are in; weighting this season 3x beat 1x and 2x. Misses
(FGMI ...) need no projection: they come from the projected attempts and makes.
"""

import pandas as pd

from ingest.projections.games import BONUS, played, with_bonus

SEASON_WEIGHTS = (3.0, 1.0, 0.5)  # this season, last season, the one before
PRIOR_GAMES = 10.0


def bonus_rates(games: pd.DataFrame, season: int, weights=SEASON_WEIGHTS,
                prior_games: float = PRIOR_GAMES) -> tuple[pd.DataFrame, pd.Series]:  # fmt: skip
    """Per-game projected bonuses: a frame indexed by player_id with one column per
    BONUS stat, for every player with games in the weighted seasons, and the league's
    rates (a Series by stat) for anyone else. games: game rows (League Lab names) for
    `season` and the seasons before it."""
    weight = {season - i: w for i, w in enumerate(weights)}
    rows = with_bonus(played(games.loc[games["season"].isin(list(weight))]))
    if rows.empty:
        return pd.DataFrame(columns=BONUS).rename_axis("player_id"), pd.Series(0.0, index=BONUS)
    rows = rows.assign(w=rows["season"].map(weight))
    out, leagues = {}, {}
    for stat in BONUS:
        known = rows.loc[rows[stat].notna()]  # fouls are missing for the oldest loads
        events = (known[stat] * known["w"]).groupby(known["player_id"]).sum()
        games_w = known["w"].groupby(known["player_id"]).sum()
        league = (known[stat] * known["w"]).sum() / known["w"].sum() if len(known) else 0.0
        out[stat] = (events + prior_games * league) / (games_w + prior_games)
        leagues[stat] = league
    return pd.DataFrame(out).rename_axis("player_id"), pd.Series(leagues)


def add_bonus(lines: pd.DataFrame, rates: pd.DataFrame, league: pd.Series) -> pd.DataFrame:
    """Projected lines (League Lab names, a player_id column) with each BONUS stat."""
    out = lines.drop(columns=[b for b in BONUS if b in lines]).merge(
        rates, left_on="player_id", right_index=True, how="left"
    )
    return out.fillna({stat: float(league[stat]) for stat in BONUS})
