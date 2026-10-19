# LeagueLabWhop: Draft Tool removed from the MVP

**Status: done on `WhopVersion` (October 18, 2026).** The Draft Tool isn't part of the
Whop MVP. Its board and its opponent model run on ESPN's ADP, ranks, projections and
auction values ([espn-data.md](espn-data.md)), and ADP has no ready replacement.

League Lab keeps it: `multi-league` and `DraftTool` are unchanged, and the personal site
still has its Draft page.

## What was removed

| Piece | Removed |
|---|---|
| The Draft page | `app/views/draft.py`, its entry in `app/Home.py`'s navigation, and the "run a mock draft" link in `app/league.py` |
| The tool's code | All of `app/draft/` (board, values, opponent model, simulation, recommendations, saved drafts) |
| Its query | `history_average` in `app/queries.py` |
| ESPN pulls | `fetch_draft_pool`, `fetch_default_pool` and `fetch_pro_schedule` in `ingest/espn_client.py`; the ingest job no longer fetches `mDraftDetail` or the 400-player pool per league |
| Transforms | The Draft section of `ingest/transform.py` (`transform_draft_pool`, `transform_draft_pool_stats`, `transform_draft_picks`, `draft_settings`) and its helpers |
| Tables | `sql/ddl/15_draft_pool.sql`, `16_draft_pool_stats.sql`, `17_draft_picks.sql`; those tables are never created in `league-lab-whop` |
| Registry | The `draft` field on each league's registry entry |
| Scripts and tests | `scripts/calibrate_draft.py`, `tests/app/test_draft.py`, the Draft tests in `tests/ingest/test_transform.py` |

The rest of the suite (233 tests) passes, and lint and format are clean.

**Side effect, a good one:** each league's daily ingest makes one fewer ESPN view call,
skips a 400-player pull, and runs three fewer BigQuery replace statements, so cost per
league drops (DML was most of League Lab's ~1.7 GB per league per run).

The Draft docs (`docs/multiLeagueDocs/draft-tool.md`, `draft-guide.md`) stay, since they
describe League Lab.

## Bringing it back later

The code is on `DraftTool` / `multi-league` (`21dca24` and earlier). To return it to the
paid product, it needs replacements for its ESPN inputs:

1. **Values and ranks** from [our projections](projections.md): the tool already
   computes PAR from a projected line.
2. **The opponent model without ESPN's ADP:** opponents draft by our ranking plus
   noise, calibrated against real drafts. A customer's own league draft results are
   league data they authorize, so they can be used for calibration.
3. **Our own ADP over time,** from customers' mock drafts.

Expect the opponent model to be less accurate at first: ESPN-league drafters lean on
ESPN's ranks, which ESPN's ADP mirrors.
