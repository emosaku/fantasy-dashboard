# Multi-league: plan

The `multi-league` branch turns the single-league dashboard into a product any ESPN
fantasy basketball league can use, at near-zero cost, and easy to shut down. It's a
**separate site**: the original league's site stays on `main` in `fantasy-dash-emk`,
permanently, and nothing migrates between them.

## Decisions (Oct 5, 2026)

| Question | Decision |
|---|---|
| Where it runs | A **new GCP project**, with its own billing, budget kill switch and IAM. Teardown can delete the whole project. |
| Sign-in | **Streamlit's built-in Google sign-in** (`st.login`, a Google OAuth client) plus **Firestore** for users, leagues, memberships and invites. |
| League formats in Phase 1 | **Any head-to-head categories league**: any category set (turnovers, 3PT%, double-doubles...), Most Categories or Each Category. Points and roto later. |
| The original league | Stays its own site on `main`. Not onboarded here. |

## What has to change

Found by reading the code, beyond what the proposal lists:

- **No table has `league_id`.** All 9 raw tables, all 12 views, every MERGE key and
  every query.
- **One league's scoring rules are hard-coded in 7 files** — its exact 9 categories
  (3PT% not turnovers, every category "higher is better") and Most Categories scoring:
  `app/categories.py`, the views, `analysis/objective.py`, `projection.py`,
  `rankings.py`. Other leagues score turnovers (lower is better), other categories,
  or Each Category. **Making scoring rules per-league is the largest job here.**
- **Single-league plumbing:** one `LEAGUE_ID` env var for ingest, one logins file,
  team 10 as a fallback, the project ID in queries and refresh.

## Phases and checkpoints

Each step ends with a review before the next starts.

### Phase 0 — Foundation (new project)

1. **Done (Oct 5):** the product is **League Lab**, in the new GCP project
   **`league-lab-emk`** (billed to Eni's Billing). A $5/month budget feeds a tested
   kill switch that pauses Scheduler and closes the site at 100%, and BigQuery
   queries are capped at 30 GiB/day. Details and runbook:
   [killswitch.md](killswitch.md).
2. **Done (Oct 5):** config, not constants: project, dataset, region from env
   everywhere; no `fantasy-dash-emk` default left. Summary: [phase0.md](phase0.md).

### Phase 1 — Tenancy, public leagues only (5-10 leagues)

**Built, deployed and tested (Oct 5)**: steps 1-8 below. Details, runbooks, the load
test and cost per league: [phase1.md](phase1.md). Before launch: create the Google
sign-in client, do the employer IP check, then onboard leagues for the checkpoint.

1. **League settings:** read each league's scoring from ESPN (categories, which are
   lower-is-better, scoring type, team count, season length) into a `league_settings`
   table. Everything downstream reads it instead of constants.
2. **Schema:** `league_id` and `season` on every table; partition by snapshot date,
   cluster by `league_id`; MERGE keys and the snapshot-replace scope include
   `league_id`.
3. **Category-generic analytics:** views, z-scores, all-play, ranks, projection,
   trade analyzer and rankings work from the league's category list and direction
   (turnovers sign-flipped). The original league's 9 categories become one case.
4. **Ingest fan-out:** one Cloud Run Job with parallel tasks, each taking a slice of
   leagues (`CLOUD_RUN_TASK_INDEX`); only leagues viewed in the last ~14 days;
   staggered requests with backoff; never more than daily on schedule. Refresh
   button: once an hour per league.
5. **Precomputed per-league tables:** ingest writes small result tables per league;
   the dashboard reads only those. Measure the real cost per league first (BigQuery
   bills at least 10 MB per table per query, so caching matters as much).
6. **Sign-in and onboarding:** Google sign-in; Firestore `users`, `leagues`,
   `memberships`, `invites`. A commissioner registers a **public** league (checked by
   fetching it with no cookies) and shares an invite link; members join and pick
   their team. The analyzer locks to your own team, as now.
7. **Product hygiene:** no ESPN name or logos, "not affiliated with ESPN" footer,
   privacy policy, delete-my-league button.
8. **Operations:** teardown script (stop Scheduler, delete stored data and secrets,
   put up a shutdown page); max-instances cap; a load test for users per instance.

**Checkpoint:** 5-10 public leagues onboarded; cost per league measured.

### Phase 2 — Private leagues

Cookies stored one Secret Manager secret per league (or KMS-encrypted), read only by
ingest; the commissioner's delete button removes them.

### Phase 3 — Open signup with a cap

Signup capped (100 leagues to start) with a waitlist; the cap rises only when the
cost per league looks fine.

## Being a good citizen of ESPN's servers

Gentle traffic makes both a block and a letter less likely: staggered requests,
backoff on errors, no more than daily scheduled pulls, a per-league refresh limit,
and only leagues people actually use. Non-commercial: no ads, no donations. If a
letter arrives, run the teardown script the same day.

## Open items

- **Employer IP check** — before publishing anything (Phase 1 launch at the latest).
- **Google OAuth consent screen** — needs a support email and the
  privacy policy URL. Sign-in only asks for name and email, which don't need Google's
  app review.
