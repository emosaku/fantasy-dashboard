# League Lab — Phase 1: Tenancy, public leagues

**Status: built, deployed and tested (October 5, 2026).** Two steps need you before
anyone outside can use it: create the Google sign-in client, and the employer IP check
(see [What's left](#whats-left)).

Live service: `league-lab` in `league-lab-emk` (the URL is in the Cloud Run console;
it's kept out of this public repo).

## What a person can do

1. **Sign in with Google.** League Lab only sees name, email and account id.
2. **Register a public league**: paste the ESPN league link. League Lab checks it with
   one no-login request to ESPN, and refuses it with a plain reason if it's private,
   isn't a head-to-head categories league, or scores a category it can't compute. The
   person who registers is the league's **commissioner on League Lab**; the first data
   load starts at once and takes a few minutes.
3. **Invite the league**: the commissioner shares an invite link from **League
   settings**. Members sign in, open the link and claim their team. Each team can be
   claimed once.
4. **Use the seven analysis pages** (the same as the original site): Compare, Power
   Rankings, Matchups and Luck, Transactions, Roster Strength, Trade Analyzer (locked to
   your own team; the commissioner can pick any), Player Rankings.
5. **Refresh** a league's data on demand, at most once an hour per league.
6. **Delete the league** (commissioner): every row, membership and invite is removed.

Someone in several leagues switches between them in the sidebar.

## Architecture

```
 Browser ──Google sign-in──▶ Cloud Run service `league-lab` (dashboard-sa, max 2 instances)
                               │ reads only m_* tables, one league at a time
                               │ reads/writes Firestore: users, members, leagues
                               │ starts the job: refresh / first load / purge
                               ▼
 Cloud Scheduler 05:30 AZ ─▶ Cloud Run Job `league-ingest` (ingest-sa, 2 parallel tasks)
                               │ leagues viewed in the last 14 days, split across tasks
                               │ polite ESPN client: pauses, backoff, 2-8 s between leagues
                               ▼
                    BigQuery `league_lab`: raw tables ─▶ views ─▶ m_* tables (per league)
```

## Scoring rules are data

The single-league site hard-coded one league's nine categories and Most Categories
scoring in seven files. League Lab reads every league's own rules from ESPN:

- **Categories**: each ESPN scoring item maps to a category that's either a *count*
  (PTS, REB, AST, STL, BLK, 3PM, TO, FGM, FGA, FTM, FTA, 3PA, OREB, DREB, MIN) or a
  *ratio* (FG%, FT%, 3PT%, A/TO), always recomputed from its two totals, never
  averaged (`ingest/catalog.py`). Categories ESPN doesn't give per-game averages for
  (double-doubles, triple-doubles) are refused at registration for now.
- **Direction**: ESPN's `isReverseItem` marks lower-is-better categories (turnovers).
  Everything compares a *score* that flips those, so "higher wins" holds everywhere:
  all-play, ranks, z-scores (fewer turnovers = positive z), the trade analyzer's
  objective, the projection and the ▲/▼ arrows.
- **Scoring type**: Most Categories ranks and projects on matchup records; Each
  Category on category records. Luck compares actual and all-play at the same level.
  ESPN names Each Category `H2H_CATEGORY`; League Lab stores it as `H2H_EACH_CATEGORY`
  (`catalog.scoring_type`), so both spellings register.

The original league's nine categories are now just one case (`NINE_CAT_NO_TO` in the
tests). New tests cover turnovers, A/TO, Each Category and unsupported formats.

## Data and ingest

- **Every table has `league_id` and `season`**, clustered by `league_id`. Current-state
  tables (settings, categories, teams, rosters, free agents, player stats, player
  details) are replaced per league each run; matchup results and transactions
  accumulate (only the last two weeks and new activity are re-fetched).
  Past-season games played are shared across leagues.
- **Loads are staged then swapped**: rows go to a temporary staging table, then one
  `DELETE` of that league's rows and one `INSERT`.
- **Precomputed tables**: after loading, each task refreshes the ten `m_*` tables for
  the leagues it loaded, in one batch. The dashboard reads only those, with the league
  as a query parameter, so a page can't read another league's rows.
- **Fan-out**: the job runs 2 parallel tasks (`CLOUD_RUN_TASK_INDEX`); each takes every
  other league. Only leagues opened (or registered) in the last 14 days are refreshed.
- **Registry**: Firestore `leagues/{id}` holds status, categories, scoring type,
  teams, season length and progress markers; ingest rewrites it every run, so the
  dashboard never asks BigQuery for a league's rules.

## Sign-in and tenancy

- **Sign-in**: Streamlit's built-in OpenID Connect with Google (`st.login()`). Its settings
  live in Secret Manager and are mounted as `secrets.toml`. For local work,
  `DEV_AUTH_EMAIL` in `.env` signs you in as that address; it's ignored on Cloud Run.
- **Rules** (`app/tenancy.py`, tested against an in-memory Firestore):
  - Up to 10 leagues on the site and 3 per person (`MAX_LEAGUES`, `MAX_LEAGUES_PER_USER`).
  - A league can be registered once; others join by invite. The commissioner can
    replace the invite link, remove members and delete the league.
  - Refresh: once an hour per league, counting the last data load too.
  - Opening a league stamps `last_viewed_at` (at most hourly), which keeps it on the
    daily refresh.
- **Caching**: every query is cached by (league, last data load), so new data shows up
  as soon as it lands, without clearing anything by hand.

## Product hygiene

- No ESPN name or logo in the product's name or branding. A footer on every page reads
  "not affiliated with, endorsed by or sponsored by ESPN or the NBA".
- A privacy policy at `/privacy`, reachable signed in or out.
- Non-commercial: no ads, no payments.
- Delete-my-league button; deleted leagues are purged by the job within minutes.

## Operations

**Deploy the dashboard** (from the repo root):

```bash
gcloud run deploy league-lab --source . --region us-west1 --project league-lab-emk \
  --service-account dashboard-sa@league-lab-emk.iam.gserviceaccount.com \
  --allow-unauthenticated --min-instances 0 --max-instances 2 --concurrency 40 \
  --cpu 1 --memory 1Gi --timeout 3600 --session-affinity \
  --set-env-vars GCP_PROJECT_ID=league-lab-emk,BIGQUERY_DATASET=league_lab,BIGQUERY_LOCATION=us-west1,GCP_REGION=us-west1,INGEST_JOB=league-ingest,SEASON=2027,MAX_LEAGUES=10,MAX_LEAGUES_PER_USER=3
```

**Deploy the ingest job**: `gcloud run jobs deploy league-ingest --source ingest
--region us-west1 --project league-lab-emk` (keeps its env vars, 2 tasks, `ingest-sa`).

**Schema changes**: `python scripts/apply_sql.py --project league-lab-emk --dataset league_lab`.

**Teardown** (e.g. a cease-and-desist): `python scripts/teardown.py --project
league-lab-emk` shows what it will do; add `--yes` to pause the schedule, put up the
shutdown page, delete every stored credential, the BigQuery dataset and the Firestore
registry. Delete the project afterwards to remove everything.

**Load test**: `python scripts/load_test.py <url> --users N --pages ...` drives real
Streamlit sessions over the websocket.

## Verification

| Check | Result |
|---|---|
| Tests | 93 pass (app math, analysis, projection, tenancy, onboarding, catalog, transforms, loader SQL, registry, kill switch) |
| Every page, real data | All 12 pages render for the test league; mock trade, waiver moves, results lens, free-agent filter and invite page exercised |
| Registration checks | A private league and a wrong id are refused with the right message |
| Live service | Healthy; signed-out pages render with 0 errors |
| Load | One instance: 20 sessions clicking continuously render in ~1.4 s median; memory ~250 MB + ~6 MB per session. Real visitors click every 10-30 s, so 2 instances serve roughly 40-50 people at once |
| Cost per league | Ingest bills ~1.7 GB of BigQuery per league per daily run (almost all of it the 10 MB minimum on each DML statement). That is ~50 GB/month per active league, so the free 1 TB/month and the 30 GiB/day cap cover about 18 active leagues. Storage: ~1.3 MB per league. Dashboard reads: ~10 MB per query, cached per data load. |

The cost figure matters for Phase 3: past ~15 leagues, the per-league DML should be
batched (one load per table per task for all its leagues) before raising the cap.

## What's left

1. **Create the Google sign-in client** (Cloud Console, can't be scripted):
   1. *APIs & Services → OAuth consent screen* in `league-lab-emk`: app name "League
      Lab", External, support email, privacy policy URL `https://<service-url>/privacy`.
      Scopes: openid, email, profile only (no Google review needed).
   2. *Credentials → Create credentials → OAuth client ID*, type Web application,
      redirect URI `https://<service-url>/oauth2callback`.
   3. Give Claude the client id and secret (or put them in Secret Manager yourself)
      as a secret `league-lab-auth` holding:
      ```toml
      [auth]
      redirect_uri = "https://<service-url>/oauth2callback"
      cookie_secret = "<long random string>"
      client_id = "<client id>"
      client_secret = "<client secret>"
      server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
      ```
      and mount it: `gcloud run services update league-lab --region us-west1
      --project league-lab-emk --update-secrets /root/.streamlit/secrets.toml=league-lab-auth:latest`
      (grant `dashboard-sa` Secret Accessor on that one secret first).
2. **Employer IP check** before telling anyone about it.
3. **Checkpoint**: onboard 5-10 public leagues and re-measure cost per league.

Known limits: invite links don't survive the Google sign-in redirect (sign in, then
open the link again); a league needs to be public on ESPN; categories without ESPN
per-game averages (DD, TD) aren't supported yet.
