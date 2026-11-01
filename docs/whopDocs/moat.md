# LeagueLabWhop: the product moat

**November 1, 2026.** Online copy: https://claude.ai/artifact/1Lzk9DNzP7T3dJ6oTJYHi7.
Read this before planning feature work: it says what makes League Lab worth paying for
and how the backlog ([backlog.md](backlog.md)) is ordered because of it.

## Summary

League Lab wins a sale over Basketball Monster (about $70 a season), Dynatyze Pro ($50
a year) and the free tools on four things: **league history nobody else has**, **a
trade finder that brings opportunities to you**, **luck analysis** and **Lock / Swing /
Punt category tiers**.

**Prioritization rule:** deepen a moat feature first; keep table-stakes features
(player rankings, power rankings, compare, injury-aware projections) competitive
without gold-plating; everything else only when those two are solid.

One finding changes the plan. The history moat is only partly real today: League Lab
keeps weekly matchup results and transactions, but ESPN keeps those too. It overwrites
rosters, standings, stat lines and injuries every morning. The history only League Lab
can have, what every league looked like on each day, isn't being saved yet. Saving it
is the one moat item that has to start before the first customer, because a day not
saved can never be recovered.

## Where each moat stands today

| Moat | Built today | Gap |
|---|---|---|
| 1. League history | Weekly category results and points per matchup, every transaction, every NBA box score, every nightly projection run | Rosters, standings, stat lines, fantasy values and injuries are replaced each morning, so no day-by-day history. A competitor can rebuild matchups and transactions from ESPN too. Deleting or lapsing a league deletes its history |
| 2. Trade finder | Waiver pickups and win-win trades ranked by category wins, plain-text reasons, a mock trade with health and games history (Trade Analyzer, categories and points) | Only when the user opens the page; nothing is pushed to them |
| 3. Luck analysis | All-play records and expected vs actual wins (Matchups & Luck, categories and points) | Not yet in the standings as a "deserved" ranking; no weekly recap |
| 4. Lock / Swing / Punt | Every team ranked per category with tiers (Roster Strength, categories) | Categories leagues only; no punt optimizer; no tracking over time |

The brief this doc is built from described a categories-only tool for one 14-team
league priced at $29-49 per league per season. The Whop version now supports points
leagues and many leagues, and its price is still open (backlog R4).

## The four moats

### 1. League history nobody else has (the core moat)

**What it is:** a record of each league, kept by the daily refresh, of things ESPN's
site shows only as they are right now.

**Why it can't be copied:** history exists only from the day a league's refresh
started; a competitor launched next year can't fetch last November. That's only true
for what ESPN itself doesn't keep, so the moat is the **daily snapshots**: each team's
roster, standings, category ranks, every player's stat line and fantasy value, and
injury status, as they were each morning.

**How we deepen it:**
- **Daily snapshots** of rosters, standings and category ranks, and player values per
  league: the foundation for everything below.
- **Hindsight trade grading:** grade every past trade by what happened after it,
  against what it looked like on the day.
- **Manager profiles** from the transaction log: who trades, streams, punts, panics.
- **Season archives and "on this date last year"** views.
- **Past seasons at sign-up:** ESPN still serves a league's past seasons, so a new
  league can arrive with its earlier results already loaded.

### 2. A trade finder that brings opportunities to you

**What it is:** instead of grading a trade the user types in (what every competitor
does), League Lab finds waiver pickups and trades that help both sides, ranked by
category wins gained, explained in plain words, with a mock trade showing health and
games-played history.

**Why it can't be copied easily:** "type in a trade, get a grade" is a commodity; a
daily list of opportunities you didn't know existed is not, and it improves as history
accumulates.

**How we deepen it:**
- **Daily opportunities digest:** each morning's new win-win trades and pickups,
  ranked and explained, by email.
- **Counter-offer generator:** for a lopsided offer, the smallest change that makes it
  fair for both sides.
- **Watchlist alerts:** tell me when a trade I wanted becomes possible (an injury, a
  slump, a schedule shift).

### 3. Luck analysis

**What it is:** each team's record if it had played every other team each week
(all-play), giving expected wins to compare with actual wins. Almost no tool measures
luck; ours uses the whole season's weekly results.

**How we deepen it:**
- **"Deserved" standings:** power rankings adjusted for luck.
- **Regression candidates:** teams and players most likely to come back to earth.
- **Weekly luck recap** in plain words, for the league chat.

### 4. Lock / Swing / Punt tiers

**What it is:** every team ranked in every category, each category tiered Lock, Swing
or Punt: punt strategy packaged as a recommendation, where competitors show ranks.

**How we deepen it:**
- **Punt optimizer:** which categories to punt, and the standings places gained.
- **Tier changes over time** (needs the daily snapshots).
- **Draft-day punt targets**, with the Draft Tool's return.
- **A points-league equivalent**, since tiers exist for categories leagues only.

## Rules that protect the moat

- **The daily refresh never stops and never breaks history.** Any change to the
  ingest keeps re-running safe (running twice gives the same rows) and keeps every
  table's columns and meaning. A history table is never dropped or reshaped without a
  migration that keeps its rows.
- **History outlives a lapsed subscription, within the privacy policy.** Today a
  deleted or lapsed league loses all its rows. Proposal: on lapse, stop refreshing but
  keep the league's history for a set time (say 12 months) so a returning customer
  finds it intact; delete on request, or sooner if the lawyer says so. Changes R12 and
  R16.
- **The analysis code stays separate from the pages.** The trade, waiver and
  projection math in `app/analysis/` and `app/points/` is plain, tested Python any
  future app or API would call. Logic doesn't move into page code; a function's inputs
  and outputs don't change without updating callers and tests.
- **Moat features don't get watered down.** A change that makes the trade finder a
  plain trade grader, or swaps history for a single snapshot, is flagged first.
- **Secrets stay secret.** ESPN login cookies, API keys and sign-in secrets are never
  committed, logged or printed.

## What this changes in the backlog

The four moat features already exist, so the MVP can sell on them as built. Only work
that loses something forever if it waits moves before release (M1, M2); the rest of
the moat work (M3-M14) leads the list after release. See [backlog.md](backlog.md).
