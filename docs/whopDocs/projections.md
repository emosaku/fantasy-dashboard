# LeagueLabWhop: our own projection model

**Status: plan (October 18, 2026).** The Whop version replaces ESPN's projections
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

A simple, explainable system in the style of baseball's Marcel:

1. **Per-minute rates.** For each stat, the player's per-minute rate in each of the
   last 3 seasons, weighted 5/4/3 toward the most recent season. Percentages come
   from projecting makes and attempts separately, so FG% and FT% follow from them.
2. **Regression to the mean.** Add a fixed amount of league-average minutes (a tuning
   value; start around 1,000) to every player's history. A rookie or bench player with
   little history lands near the average; a starter with 7,000 minutes barely moves.
3. **Aging.** A multiplicative adjustment per stat by age, fit from the history itself
   (how each age group's rates changed year over year). Expect gains into the mid-20s
   and decline past about 30.
4. **Minutes and games, separately.** Minutes per game from weighted recent minutes,
   regressed toward the player's role. Games from his games-played history (the
   ingest job already keeps 3 seasons of it in `player_seasons`), with a haircut for
   injury history.
5. **Line = rates x minutes x games.** Fantasy points then come from each league's own
   point values (`computed_points` in `ingest/transform.py`), and categories from the
   same line.

**Known gaps in v1:** players who changed teams or roles (we add a small manual
override table), and rookies with no NBA history (league-average-for-rookies, flagged
as low confidence on the pages).

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

| Piece | Where |
|---|---|
| Stats source client and the 3-season backfill | `projections/source.py` *(new)* |
| The model (rates, regression, aging, minutes, games) | `projections/model.py` *(new)* |
| In-season blend | `projections/blend.py` *(new)* |
| Backtest, runnable as a script | `projections/backtest.py`, `scripts/backtest_projections.py` *(new)* |
| Output table | BigQuery `projections` (player_id, season, made_at, model_version, per-game line, minutes, games) |
| Into the app | The ingest job writes our line into the `projected` stat window that the pages already read, in place of ESPN's |
| Nightly run | A step in `league-ingest`, or its own small Cloud Run job if it outgrows it |
| Tests | `tests/projections/` *(new)* |

## Phases

0. **Source.** ALL-STAR chosen and ESPN's 2026-27 preseason projections saved
   (`espn_projection_snapshot`, 349 players, October 19). Left: the trial checks above,
   then the backfill and the per-game and window views.
1. **Model and backtest.** Backfill, build the model, run the backtest and tune until it
   meets the ship bar.
2. **Into the app.** Swap the `projected` window to our model; check every page that
   reads it (Compare, Trade Analyzer, Roster Strength, Power Rankings' projected
   finish, the points pages).
3. **In season.** The nightly blend.
4. **Show the work.** A "How our projections work" page: a selling point, and honest.
