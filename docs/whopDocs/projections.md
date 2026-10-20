# LeagueLabWhop: our own projection model

**Status: model built and tested on synthetic data (October 19, 2026); waiting on real
data.** The Whop version replaces ESPN's projections
with our own. Everything downstream (PAR, roster strength, trade values, projected
standings) already runs on "a projected stat line per player", so the model replaces
one input and the math above it stays as it is.

## Why

ESPN's projections are ESPN's editorial product. A user can authorize us to read their
own league, but not to resell ESPN's forecasts. See [espn-data.md](espn-data.md) for the
full field-by-field split. The model is also the part customers pay for, so we should
own it and be able to explain it.

## What it needs (not box scores)

Season-level lines per player for the last 3 seasons: games, minutes, PTS, REB (OREB,
DREB), AST, STL, BLK, TO, 3PM/3PA, FGM/FGA, FTM/FTA, plus birth date. Season totals
or per-game averages are enough for the preseason model. Game logs are only needed
later, for in-season updates and "last 15 days" style views.

**Source: BallDontLie ALL-STAR** ($9.99/month or $95.90/year, NBA only; decided
October 19, 2026). It serves per-game player stats, active players and injuries; we
build everything else ourselves instead of paying for GOAT ($39.99/month) season
averages and advanced stats. Its terms allow commercial use, storing and caching, with
no attribution; they forbid reselling the raw data unmodified or running a competing
data service, and neither applies to this product.

**What we calculate: only what League Lab uses today**, nothing more:

| What | Built from |
|---|---|
| Per-game PTS, REB, OREB, DREB, AST, STL, BLK, TO, 3PM, 3PA, FGM, FGA, FTM, FTA, MIN | Each player's game rows: total / games played |
| GP | Count of games with minutes > 0 |
| Windows `season`, `last_30`, `last_15`, `last_7` | The same, over games in that many days (ESPN's windows today) |
| FG%, FT%, 3PT%, A/TO | Already computed from totals by the app (`ingest/catalog.py`), so nothing new |
| Games played per past season (`player_seasons`) | Season's GP, for the last 3 seasons |
| Injury status | ALL-STAR's injuries endpoint |
| Projected line (`projected`) | The model below, from the rows above |

No advanced stats (usage, PER, pace), team averages or standings: League Lab doesn't
use them. The model needs one non-stat input, each player's birth date, for aging.

**Check during the 48-hour trial** before paying: the players endpoint has birth
dates; game rows have minutes and the team the player played for that night; how
games a player missed appear (no row, or a 0-minute row); every scheduled game has
rows; rows per request, to time the 3-season backfill against 60 requests a minute.

## The model

A simple, explainable system in the style of baseball's Marcel
(`ingest/projections/model.py`):

1. **Aging first.** Each past season is moved to the player's age in the target
   season, stat by stat, along an aging curve fit from the history itself: how each
   age's per-minute rates changed the next season, for players with 500+ minutes in
   both. Ages with few such players are pulled toward "no change". Players without a
   birth date skip this step.
2. **Per-minute rates.** For each stat, the last 3 seasons weighted 5/4/3 toward the
   most recent (scaled so last season counts 1.0, so every prior below reads in
   last-season terms). Makes and attempts are projected separately, so FG%, FT% and
   3PT% follow from them.
3. **Regression to the mean, fit per stat.** Every history gets some minutes of
   league-average play added. How many is estimated from the data for each stat
   (empirical Bayes): how much players' rates spread out, minus what chance alone
   explains. Stable stats like shot attempts barely regress; noisy ones like steals and
   blocks regress more. One overall multiplier is tuned by the backtest.
4. **Minutes and games, separately.** Minutes per game lean harder on last season (6/3/1):
   a role carries over more than per-minute production does. Both are pulled toward
   a typical rotation player (18 minutes, 60 games), and games are capped at 82.
5. **Line = rates x minutes, plus games.** Fantasy points come from each league's own
   point values, and categories from the same line.

**Known gaps in v1:** players who changed teams or roles (a small manual override
table later), a season missed entirely to injury (no rows, so it isn't counted as zero
games), and rookies with no NBA history (not projected yet).

## In season

Once games are played, blend the preseason projection with season-to-date rates,
weighting the season-to-date side by minutes played. This is the same regression idea:
the preseason projection acts as a prior worth a fixed number of minutes. The blend
updates nightly with the ingest run.

## How we'll know it's good enough: the backtest

- **Setup.** For each of 2023-24, 2024-25 and 2025-26: fit using only earlier seasons,
  project that season, compare with what actually happened for players with 500+
  minutes.
- **Measures.** Error per stat (mean absolute error), error in fantasy points per game
  under ESPN's default points scoring, and the rank correlation of the top 150 players
  (what a fantasy manager actually feels).
- **Baselines.** It must clearly beat "repeat last season", and land close to ESPN's own
  projections.
- **ESPN comparison, done now.** ESPN's API only serves the current season's
  projections, so **snapshot ESPN's 2026-27 preseason projections before the season
  starts (around October 20)** and score both against the 2026-27 actuals as the season
  goes. That snapshot is an internal benchmark only: never shown to users.
- **Ship bar.** Beats the baseline on every main stat and within about 5% of ESPN's
  fantasy-points error. If it falls short, tune the regression and aging before
  shipping, not after.

## Where it lives

The code is in `ingest/projections/`, because the ingest job's image only packages
`ingest/` and the nightly run belongs to that job.

| Piece | Where | Status |
|---|---|---|
| Game rows -> season lines and the season / last 30 / 15 / 7 windows | `ingest/projections/games.py` | Built |
| The model (aging, rates, regression, minutes, games) | `ingest/projections/model.py` | Built |
| In-season blend | `ingest/projections/blend.py` | Built |
| Backtest and tuning | `ingest/projections/backtest.py`, `scripts/backtest_projections.py` | Built |
| Tables | `nba_player_games`, `nba_players`, `projections` (`sql/ddl/15-17`) | Created in `league-lab-whop`, empty |
| BallDontLie client and the 3-season backfill | `ingest/projections/source.py` | Needs the API key |
| Matching BallDontLie players to ESPN player ids | `nba_players.espn_player_id` | Needs the data (by name and team) |
| Into the app | The ingest job writes our line into the `projected` window the pages already read | Phase 2 |
| Tests | `tests/projections/` (26 tests) | Built |

## Synthetic check (October 19)

Until real data is loaded, the tests run on a synthetic league with known talent:
500 players over 10 seasons with real-world-sized noise, talent and minutes that drift
from year to year, and an aging curve (+4%/year to 26, flat to 30, -5%/year after).
The model recovers the aging curve's shape, regresses steals and blocks more than
shot attempts, and beats "repeat last season" in every test season:

| Season | Fantasy pts/game error, model | Repeat last season | Rank correlation, top 150: model | Repeat last season |
|---|---|---|---|---|
| 2024 | 3.90 | 3.99 | 0.76 | 0.75 |
| 2025 | 3.93 | 4.16 | 0.75 | 0.75 |
| 2026 | 4.02 | 4.08 | 0.76 | 0.73 |

That proves the machinery works, not that the model is good: only the real backtest
can show that. Two lessons from building it, both now in the model: aging has to move
each past season to the target age (aging only the last year left projections about a
year and a half behind), and minutes need their own heavier recency weights.


## Phases

0. **Source.** ALL-STAR chosen and ESPN's 2026-27 preseason projections saved
   (`espn_projection_snapshot`, 349 players, October 19). Left: the trial checks above,
   then the backfill and the per-game and window views.
1. **Model and backtest.** Model, blend, backtest and tuning built and tested on
   synthetic data. Left: the backfill, then `scripts/backtest_projections.py --tune` on
   real seasons until it meets the ship bar.
2. **Into the app.** Swap the `projected` window to our model; check every page that
   reads it (Compare, Trade Analyzer, Roster Strength, Power Rankings' projected
   finish, the points pages).
3. **In season.** The nightly blend.
4. **Show the work.** A "How our projections work" page: a selling point, and honest.
