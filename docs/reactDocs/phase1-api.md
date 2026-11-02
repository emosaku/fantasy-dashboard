# League Lab React rebuild: Phase 1, the API foundation

**November 1, 2026.** Online copy: https://claude.ai/artifact/8HXk9P4odHnp1UtJjyMPZo.

## Summary

Phase 1 is built and tested on branch `ReactFrontend`: a FastAPI layer over the
existing engine for both league formats, a trade finder cache, week-over-week history
views over the daily snapshots, and both spikes written up. Nothing was deployed, and
no new SQL has run on the live dataset yet; it's waiting for review (below).

| Phase 1 checklist | Status |
|---|---|
| Every endpoint has a test; median response under 200 ms from cache | Done: 40 tests; median 5 ms on real data |
| A league you don't belong to returns 403 | Done, tested on every league endpoint |
| The daily ingest and nightly NBA update still run green | Done: neither was touched (code, tables, schedules unchanged); latest runs green |
| History view returns week-over-week rank changes | Done: three views, checked on real snapshots |
| Spike: Whop sign-in for Streamlit and the API (R9) | Done: **yes, use Whop** |
| Spike: private leagues by bookmarklet | Done: **no**; public leagues at launch, a browser extension later |

**Waiting on you:**

- **Review the new SQL** (one table, three views; none change anything running today).
  Say go and it gets applied to `league-lab-whop`.
- **Create a Whop developer app** (client id and redirect URL) for Phase 2's sign-in.
- **A question about the points engine.** Its trade finder flags a deal as lopsided
  only when *you* overpay (`points.trades.score_pair`: what I give vs what I get), never
  when the partner does. On real data it offered Dyson Daniels and Cedric Coward for
  Luka Doncic as a win-win. The categories engine checks both directions
  (`abs(give - get)`). The API matches today's Streamlit behavior; fixing it changes
  engine math, so it's a decision. Recommendation: two-sided, like categories.

## The API

A FastAPI app in `api/` that the React app will call for everything; it holds no math
of its own. Every number comes from the functions the Streamlit pages call
(`app/analysis/` for categories leagues, `app/points/` for points leagues), and every
endpoint answers in the league's format, with a `format` field.

| Piece | What it does |
|---|---|
| `api/engine.py` | The glue to the engine: the calls `analyzer.py` and `points/data.py` make, without Streamlit |
| `api/services.py` | Per-league work, cached in memory by data version: players and totals per window, the points simulation per window and day, the trade finder, points waivers |
| `api/store.py` | Firestore (leagues, memberships, saved trades) and BigQuery (league tables, history, finder cache) behind one interface; tests swap in fixtures |
| `api/context.py` | Who's calling and which league: the 401 / 403 / 404 / 409 rules |
| `api/routes/` | The endpoints |
| `api/precompute.py` | The morning finder warm-up |
| `app/reads.py` (new, shared) | The one BigQuery read both front ends use; Streamlit's `queries.py` now calls it, same query and results |

| Endpoint (under `/api`) | Returns | Wraps |
|---|---|---|
| `GET /me`, `GET /leagues` | User and leagues | `tenancy.memberships` |
| `GET /leagues/{id}` | Rules, teams, windows, my team, uncounted stats, freshness | registry, `onboarding.uncounted_labels` |
| `GET /leagues/{id}/standings` | Records and standings | `teams` |
| `GET /leagues/{id}/power-rankings` | All-play ranks, projected finish | `m_power_rankings` + `project_season`; points: `season_table`, `projected_finish` |
| `GET /leagues/{id}/luck` | Actual vs all-play by week | `m_luck`; points: `luck_by_week` |
| `GET /leagues/{id}/matchups?week=` | A week's matchups | `m_team_week_cats`, `m_luck`; points: `matchup_scores` |
| `GET /leagues/{id}/matchups/compare?a=&b=&week=` | Two teams side by side | same |
| `GET /leagues/{id}/roster-strength?window=` | Strength, ranks, Lock / Swing / Punt tiers | `m_roster_strength`, `m_category_ranks`, `compute_weights`; points: simulation, `points_by_source` |
| `GET /leagues/{id}/players?window=&position=&q=&hide_injured=` | Rankings heatmap | `player_rankings`; points: FP/G |
| `GET /leagues/{id}/players/{pid}` | One player | `m_player_pool`, `m_player_z` or `player_points`, `m_player_profile` |
| `GET /leagues/{id}/history?metric=&start=&end=` | Day-by-day history, week-over-week change | the history views |
| `GET /leagues/{id}/trade-finder?team=&window=&delta=&overrides=` | Win-win trades, verdict, reason, pitch | `analysis.trades.find_trades`; points: `points.trades.find_trades` |
| `GET /leagues/{id}/waiver-wire?team=&window=` | Best add / drop moves | `rank_waiver_moves`; points: `waiver_moves` |
| `POST /leagues/{id}/trades/analyze` | Mock trade: verdict, then the numbers | `simulate_trade`; points: `points.trades.mock` |
| `GET / POST / DELETE /leagues/{id}/saved-trades` | Saved trades | `saved_store` |
| `GET /leagues/{id}/transactions?start=&end=&team=&type=` | Activity log, newest first | `m_transactions` |
| `POST /leagues/{id}/refresh` | Start a refresh (at most hourly) | `tenancy.claim_refresh`, `refresh.ingest_league` |
| `POST /onboarding/preview` | Register-page check | `onboarding.preview` |
| `POST /onboarding/register-league` | Register a public league, start its first load | `tenancy.register` |

Verdicts use one rule for both formats, the engine's (`points.trades.status`): good for
me and not worse for them = win-win; good for me but worse for them or lopsided = they
say no; otherwise it costs you. `/docs` serves the live schema.

## Sign-in and access

Every request carries an OpenID Connect ID token (`Authorization: Bearer ...`),
checked in `api/auth.py`. The provider is configuration: `OIDC_ISSUER` and
`OIDC_AUDIENCE`. Signing keys come from the issuer's discovery document; a token must
be signed by one, unexpired, from that issuer, for our audience. The user id is the
token's `sub`, the same id Streamlit's sign-in stores, so both front ends share
memberships.

| Case | Answer |
|---|---|
| No token, bad signature, wrong issuer or audience, expired | 401 |
| A league you're not a member of | 403 |
| Another team's recommendations, unless commissioner | 403 |
| A league being deleted or missing | 404 |
| First data load not landed; no team picked for a recommendation | 409 |

Tests use a test issuer with its own key (real signed tokens). Locally,
`DEV_AUTH_EMAIL` stands in for sign-in, refused on Cloud Run. Tokens are never logged.

## Trade finder cache and history views

**Finder cache:** `trade_finder_cache`, one row per league, team and window, the API's
JSON rows, valid only for its data load (`data_version`). Written by
`api/precompute.py` after the morning refresh, or on the first request after a load;
other searches (swing size, overrides) are computed fresh. The warm-up job's deploy is
Phase 6.

| View | One row per | Change |
|---|---|---|
| `v_rank_history` | league, day, window, team, category (categories) | `rank_change` (positive = up) |
| `v_standing_history` | league, day, team | `standing_change` |
| `v_player_value_history` | league, day, window, player: total z or FP/G, rank in the pool | `rank_change` |

Checked on real snapshots a week apart: every later-day row found its week-ago rank,
and the 280 ranks changed on purpose all showed the change.

## New BigQuery SQL to review

None of this has run on `league-lab-whop`; it ran only in a throwaway dataset
(deleted). To apply after review:
`python scripts/apply_sql.py --project league-lab-whop --dataset league_lab`.

| File | Creates | Effect on what runs today |
|---|---|---|
| `sql/ddl/21_trade_finder_cache.sql` | Table `trade_finder_cache` | None: only the API writes it |
| `sql/views/12_v_rank_history.sql` | View over `snap_category_ranks`, joined 7 days earlier | None |
| `sql/views/13_v_standing_history.sql` | Same over `snap_standings` | None |
| `sql/views/14_v_player_value_history.sql` | Each player's daily value and pool rank, joined 7 days earlier | None |

## Spike: sign in with Whop (R9)

**Yes: Whop is a standard OpenID Connect provider. Recommendation: use it, and drop
the Google sign-in plan** (one account for buying and signing in, no Google app
verification).

| Need | Whop |
|---|---|
| Discovery and keys | Issuer `https://api.whop.com`, `/.well-known/openid-configuration`, keys at `/.well-known/jwks.json` (two ES256 keys) |
| ID token | ES256; `sub`, `email`, `name`, `aud` among its claims |
| Scopes | `openid`, `profile`, `email` |
| Flow | Authorization code with PKCE (S256); client secret or public client |
| Membership | Not in the token: `/api/v1/users/{id}/access/{product_id}` (`has_access`), or the R11 webhook record |

Tested live: `api/auth.py` loaded Whop's keys through discovery and refused a forged
token; a unit test accepts an ES256 token like Whop's. Plugging in:
`OIDC_ISSUER=https://api.whop.com`, `OIDC_AUDIENCE=` the Whop app's client id. Needs a
Whop developer app; its secret goes in Secret Manager. Signing in proves who someone
is, not that they've paid; payment comes from R11.

Sources: [Whop OAuth guide](https://docs.whop.com/developer/guides/oauth),
[discovery document](https://api.whop.com/.well-known/openid-configuration),
[Check user access](https://docs.whop.com/api-reference/beta/users/check-user-access).

## Spike: private leagues by bookmarklet

**No: ESPN marks `espn_s2` and `SWID` HttpOnly, hidden from any page script.**
Recommendation: public leagues at launch (R15); a browser extension if private leagues
come later.

| Option | Daily refresh | Catch |
|---|---|---|
| Make the league public (launch) | Yes | One setting; nothing secret stored |
| Browser extension, cookie permission (later) | Yes | Build and store review; not iPhone Safari; we hold ESPN logins (lawyer) |
| Copy from developer tools (today's app) | Yes | Desktop only, fiddly; we hold ESPN logins |
| Sync bookmarklet that posts the league data, not the cookies (untested) | No: when clicked | Nothing stored, but only as fresh as the last click; ESPN's server behavior untested |

Sources: [TFN Connect for ESPN](https://addons.mozilla.org/en-US/firefox/addon/tfn-connect-for-espn/),
[ffscrapr: ESPN private leagues](https://cran.uni-muenster.de/web/packages/ffscrapr/vignettes/espn_authentication.html).

## Tests, speed and running it

40 new tests in `tests/api/` (categories and points fixtures, real signed tokens,
in-memory Firestore); where an endpoint wraps an engine function the test compares
with it directly. Whole suite: 362 passing.

On the two public test leagues (10 teams each) in a throwaway dataset:

| Call | Time |
|---|---|
| Repeat calls, all 33 endpoint and format pairs | Median 5 ms, slowest 28 ms |
| First call after a data load, most endpoints | 0.3-0.7 s |
| Power rankings, first call | 1-3 s |
| Trade finder, computed | About 6 s |
| Trade finder from the cache table, fresh server | 0.8-2 s |

Phase 6 should keep one instance warm and run the finder warm-up each morning. Bugs
the real-data run caught, fixed: pandas `NA` team ids in the mock-trade check; history
and points waivers not cached.

```
pip install -r requirements.txt -r api/requirements.txt
GCP_PROJECT_ID=league-lab-whop DEV_AUTH_EMAIL=you@example.com \
  uvicorn api.main:create_app --factory --reload
# http://localhost:8000/docs
```

Nothing was deployed; the API service, the warm-up job and CORS origins are Phase 6.
