# Google Cloud use cases in this project

This covers every GCP resource/service used in Fantasy Dashboard, what role it plays
in the architecture, and its current build status. For the six underlying APIs that
had to be enabled first, see [`gcp-apis.md`](gcp-apis.md); this doc is about the
resources built on top of them.

## Project and billing

| Resource | Use case | Status |
|---|---|---|
| **Project** `fantasy-dash-emk` | Isolates this project's resources, IAM, and billing from every other project on the account — one dashboard's worth of blast radius, not a shared sandbox. | Created |
| **Budget alert** ($5/month, 50/90/100% thresholds) | Backstop against a runaway bill — e.g. a misconfigured Cloud Scheduler job firing every minute instead of once a day. Email alert only; nothing shuts off automatically. | Created |

## Identity and access

| Resource | Use case | Status |
|---|---|---|
| **`ingest-sa`** service account | Identity for the daily ingest job. Holds *only* what it needs to pull ESPN data in and write it to BigQuery: BigQuery Data Editor, BigQuery Job User, Secret Manager Secret Accessor. | Created |
| **`dashboard-sa`** service account | Identity for the Streamlit app. Today: BigQuery Data Viewer, BigQuery Job User. Step 7 adds exactly two narrow grants: `roles/run.invoker` on the `espn-ingest` job only (the Refresh data button), and Secret Accessor on the login-hash secret only. It still can't read the ESPN cookie secrets, so it's structurally incapable of leaking them even if compromised. | Created; both Step 7 grants in place |

This two-identity split is the project's core security boundary: the ESPN session
cookies are reachable from exactly one place (the ingest job), and the
internet-facing half (the dashboard) can't reach them at all. The Refresh button can
*start* the ingest job, but the job runs as `ingest-sa`, so the dashboard still never
sees the cookies.

## Secrets

| Resource | Use case | Status |
|---|---|---|
| **Secret Manager** (`espn-s2`, `espn-swid`) | Stores the two ESPN session cookies outside of git and outside of plain env vars. Cloud Run injects them into the ingest job at runtime via `--set-secrets`; they're never baked into the container image or committed to the repo. | Created |
| **Secret Manager** `dashboard-logins` | The manager logins' salted password hashes and the stay-signed-in signing secret (`.streamlit/secrets.toml`, written by `scripts/manage_logins.py`), mounted into the dashboard service as Streamlit's global secrets file. | Live |

## Data storage

| Resource | Use case | Status |
|---|---|---|
| **BigQuery dataset** `fantasy` (region `us-west1`) | The project's database: 9 raw tables (`teams`, `matchup_categories`, `rosters`, `player_stats`, `transactions`, `free_agents`, `league_status`, `player_seasons`, `player_details`), each filled by the ingest job. Region matches Cloud Run's region to avoid cross-region query costs. | Live, filled daily |
| **BigQuery views** (`v_team_week_cats`, `v_all_play`, `v_power_rankings`, `v_luck`, `v_transactions`, `v_team_roster_stats`, `v_roster_strength`, `v_player_pool`, `v_player_z`, `v_team_category_z`, `v_category_ranks`, `v_player_profile`) | Where the set-based analysis lives — all-play, luck, player and team z-scores, category ranks — so Streamlit pages mostly `SELECT` and plot. The trade/waiver search and the season projection run in tested Python (`app/analysis/`) because they react to page controls. | Live (12 views) |

## Compute

| Resource | Use case | Status |
|---|---|---|
| **Cloud Run Job** `espn-ingest` | Runs once a day (and on demand from the dashboard's Refresh data button): pulls the league from ESPN using the Secret Manager cookies — teams, matchups, rosters, per-game stats, free agents, every activity, injury details and 3 seasons of games played — and `MERGE`s it into BigQuery. About a minute per run; billed only for those seconds. | Live |
| **Cloud Run Service** `fantasy-dash` (Streamlit dashboard) | Serves the dashboard to the league over one URL; every page sits behind a manager login. `--min-instances 0` means it scales to zero between visits — no idle cost, just a short cold start on the next view. `--session-affinity` and a 1-hour timeout keep each viewer's websocket on one instance. | Live |

## Scheduling

| Resource | Use case | Status |
|---|---|---|
| **Cloud Scheduler** job `espn-ingest-daily` | Triggers `espn-ingest` automatically every day at 5:00 AM Arizona time (after that night's games have settled), so nobody has to remember to run it by hand. Falls inside the free tier (3 jobs/month free; this project needs 1). | Live |

## Build and artifacts

| Resource | Use case | Status |
|---|---|---|
| **Cloud Build** | Builds the Docker images for both the ingest job and the dashboard directly from source — what `gcloud run jobs deploy --source` and `gcloud run deploy --source` do under the hood, no local Docker build required. | Used on every deploy |
| **Artifact Registry** | Stores those built images between deploys. | Used implicitly, same as above |

## Observability

| Resource | Use case | Status |
|---|---|---|
| **Cloud Monitoring alert** on job failures | If ESPN returns a 401 (expired cookies) or the job otherwise fails, this is what notifies you to refresh the secret — without it, a silent ingest failure just means stale data with no warning. | Live |

## CI/CD (deliberately deferred)

| Resource | Use case | Status |
|---|---|---|
| **Workload Identity Federation** + **GitHub Actions** | Lets GitHub Actions deploy to Cloud Run on push to `main` without a long-lived JSON service account key sitting in repo secrets. | Not set up — deploys are done by hand. `ci.yml` (tests on every push) needs no cloud access; the deploy workflows remain stubs. |

## Cost summary

Everything built so far (project, budget, service accounts, secrets, a season's
worth of BigQuery data, a daily one-minute Cloud Run Job, one Scheduler job) costs
**effectively $0/month** — all within free tiers. With the dashboard deployed, the
architecture is designed to stay near-zero at idle too: Cloud Run scales to zero,
Cloud Scheduler and Secret Manager both fit their free tiers at this scale, and a
season of league data is well under BigQuery's free storage tier. See the proposal's
own [cost estimate](proposal.md#timeline-cost-and-risks) — under $1/month even fully
deployed.
