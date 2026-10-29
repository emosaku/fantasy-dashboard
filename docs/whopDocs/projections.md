# LeagueLabWhop: our own projection model

**Status: model live in `league-lab-whop`'s pages (October 21, 2026); it beats ESPN's
projections on the backtest. In-season blend live October 29
([nightly-update.md](nightly-update.md)).** The Whop version replaces ESPN's projections
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

**Checked against the live API (October 19, subscription bought):**

| Check | Result |
|---|---|
| Birth dates | **Not in the API** (draft year only). Taken from Wikidata instead, below |
| Minutes | Whole minutes as text ("30"); "00" for a game he didn't play |
| Missed games | 0-minute rows, dropped before counting games played |
| Team per game | Yes, the team he played for that night (trades handled) |
| Regular season only | `season_type=regular` works; ~1,237 games a season |
| Paging and rate | 100 rows a request, 60 requests a minute: ~6 minutes a season |

The key is in Secret Manager in `league-lab-whop` (`balldontlie-api-key`), readable
only by `ingest-sa`. Ten seasons (2016-17 to 2025-26) load into `nba_player_games`
with `scripts/backfill_nba.py`.

**Birth dates and ESPN ids: Wikidata.** Wikidata records both a birth date and an
ESPN player id for nearly every NBA player (5,967 people), and its data is CC0,
public domain, so the product can use it freely. `scripts/match_players.py` matches
BallDontLie players to it by name (accents, punctuation and Jr./III ignored; shared
names settled by draft year, otherwise left unmatched) and fills in `nba_players`.
That one match gives the model its ages and links our projections to customers'
ESPN rosters.

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
4. **Minutes and games, separately.** Minutes per game come from last season alone
   (what tuning on real seasons chose): a role carries over more than per-minute
   production does. Shot volume (3PA, 3PM, FTA, FTM) follows role and range too, so its
   rates weigh recent seasons 6/3/1. Minutes and games are pulled toward a typical
   rotation player (18 minutes, 60 games), and games are capped at 82.
5. **Line = rates x minutes, plus games.** Fantasy points come from each league's own
   point values, and categories from the same line.

**Known gaps in v1:** players who changed teams or roles (a small manual override
table later), a season missed entirely to injury (no rows, so it isn't counted as zero
games), and rookies with no NBA history (not projected yet).

## In season

Once games are played, blend the preseason projection with season-to-date rates,
weighting the season-to-date side by minutes played. This is the same regression idea:
the preseason projection acts as a prior worth a fixed number of minutes. The blend
updates nightly, in the `nba-nightly` job ([nightly-update.md](nightly-update.md)).

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
| BallDontLie client (rate-limited, key in Secret Manager) | `ingest/projections/source.py` | Built |
| Season backfill | `scripts/backfill_nba.py` | 10 seasons loaded: 2016-17 to 2025-26, 1,508 players |
| Birth dates and ESPN ids | `ingest/projections/people.py`, `scripts/match_players.py` | 99.6% of minutes matched |
| Game rows -> season lines and the season / last 30 / 15 / 7 windows | `ingest/projections/games.py` | Built |
| The model | `ingest/projections/model.py` | Built, tuned |
| In-season blend | `ingest/projections/blend.py` | Built |
| Backtest and tuning | `ingest/projections/backtest.py`, `scripts/backtest_projections.py` | Built |
| Tables | `nba_player_games`, `nba_players` (loaded), `projections` (empty) | `league-lab-whop` |
| Into the app | The ingest job writes our line into the `projected` window the pages read | Phase 2 |
| Nightly update of the current season | A step in `league-ingest` | Phase 3 |
| Tests | `tests/projections/` (45 tests) | Built |

## Matching players (October 19)

BallDontLie's player list also holds other leagues' players (three "Luka Doncic"s,
two of them Real Madrid records), so only players with NBA games are matched. Two
lessons, both now in the matcher:

- **Wikidata now keeps many people's names in a language-neutral "mul" label**, not
  an English one. Querying English labels only silently dropped stars (Kevin Durant,
  Jayson Tatum); the query falls back to "mul".
- **Name variants need passes,** strictest first: "T. J." = "T.J.", suffixes dropped
  (but tried kept first, so Gary Payton II isn't his father), umlauts spelled out
  (Pöltl = Poeltl), short first names (Nic / Nicolas), and a short alias list for true
  nicknames (Bub, Bones, Ace).

Left unmatched on purpose (0.4% of minutes): two real players named Jaylin Williams,
likewise Brandon Williams, and a few duplicate BallDontLie entries. 2026 rookies match
once they play.

## Real backtest (October 19)

Tuned on 2021-22 and 2022-23 only, then scored on the three seasons after, so tuning
doesn't flatter the scores. Players with 500+ minutes; ESPN's column covers the
players in ESPN's own projection list (264 of them):

| Season | Measure | Our model | Repeat last season | ESPN |
|---|---|---|---|---|
| 2023-24 | Fantasy pts/game error | **4.25** | 4.54 | |
| 2024-25 | Fantasy pts/game error | **3.94** | 4.64 | |
| 2025-26 | Fantasy pts/game error | **4.57** | 5.00 | 4.71 |
| 2025-26 | Season fantasy points error | **487** | 559 | 520 |
| 2025-26 | Ranking of the top 150 (rank correlation) | 0.745 | 0.721 | **0.776** |

- **Against "repeat last season":** better on every one of the 15 stats in 2023-24 and
  2024-25; in 2025-26 on all but free throws (FTA error 0.803 vs 0.790).
- **Against ESPN (2025-26):** 3% lower fantasy-points-per-game error and 6% lower
  season-total error; better on 13 of 15 stats, behind on free throws (FTM, FTA). ESPN
  ranks the top players a little better.
- **The ship bar is met:** it beats the baseline on the main stats and is better than
  ESPN, not just within 5% of it.
- **Caveat:** whether ESPN's 2025-26 numbers (taken from the October 2026 snapshot) are
  its preseason projections or a later revision isn't known; a revision would favor
  ESPN, so our edge is if anything understated. The clean comparison is the 2026-27
  preseason snapshot, scored as the season plays out.

**What moved the numbers,** in order: aging each past season to the target age (the
biggest gain, and what fixed the rankings), last season's minutes alone, per-stat
regression, and 6/3/1 weights for shot volume (fixed three-pointers in 2022-23 and
2023-24). Tried and dropped: rescaling past seasons to the latest league environment
(no measurable effect).

**On a synthetic league** (500 players with known talent), used to test the code
before real data: the model recovers the aging curve and beats "repeat last season"
every season. Building it showed that aging has to move every past season, not just
the last one.

## Phases

0. **Source.** Done: ALL-STAR bought and checked, Wikidata for birth dates and ESPN
   ids, ESPN's 2026-27 preseason projections saved (`espn_projection_snapshot`).
1. **Model and backtest.** Done: 10 seasons loaded, players matched, tuned and
   backtested; it meets the ship bar and beats ESPN.
2. **Into the app.** Done and deployed October 21
   ([projections-in-app.md](projections-in-app.md)), with three fixes found on the way:
   fathers' birth dates, no aging past 38, and stars' minutes.
3. **In season.** Done October 29: the nightly blend, with a tuned start for rookies
   ([nightly-update.md](nightly-update.md)).
4. **Show the work.** A "How our projections work" page: a selling point, and honest.
