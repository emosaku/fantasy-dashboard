"""LeagueLabWhop's own projections, replacing ESPN's (docs/whopDocs/projections.md).

* games.py -- per-game player rows from the stats source into season lines and the
  season / last_30 / last_15 / last_7 windows League Lab's pages read.
* model.py -- the preseason model: weighted per-minute rates, regression to the
  league mean, aging, and minutes and games projected separately.
* blend.py -- in season: the preseason projection blended with season-to-date stats.
* backtest.py -- scores the model (and any other projections) against real seasons.

Everything here works on DataFrames and knows nothing about where the stats come from,
so the source (BallDontLie ALL-STAR) plugs in without touching the model.
"""
