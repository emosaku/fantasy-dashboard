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
| **`dashboard-sa`** service account | Identity for the Streamlit app. Holds *only* read access: BigQuery Data Viewer, BigQuery Job User. Deliberately can't touch Secret Manager — the dashboard never needs ESPN credentials, so it's structurally incapable of leaking them even if compromised. | Created |

This two-identity split is the project's core security boundary: the ESPN session
cookies are reachable from exactly one place (the ingest job), and the
internet-facing half (the dashboard, `--allow-unauthenticated`) can't reach them at
all.

## Secrets

| Resource | Use case | Status |
|---|---|---|
| **Secret Manager** (`espn-s2`, `espn-swid`) | Stores the two ESPN session cookies outside of git and outside of plain env vars. Cloud Run injects them into the ingest job at runtime via `--set-secrets`; they're never baked into the container image or committed to the repo. | Created (2 secret versions) |

## Data storage

| Resource | Use case | Status |
|---|---|---|
| **BigQuery dataset** `fantasy` (region `us-west1`) | The project's database. Holds the five raw tables (`teams`, `matchup_categories`, `rosters`, `player_stats`, `transactions`) and every analytics view that powers the six dashboard pages. Region matches Cloud Run's region to avoid cross-region query costs. | Dataset created, empty — tables are Step 3 |
| **BigQuery views** (`v_team_week_cats`, `v_all_play`, `v_power_rankings`, `v_luck`, `v_transactions`, `v_roster_strength`, `v_team_roster_stats`) | Where the actual analysis logic lives — all-play simulation, luck calculation, z-scored roster strength, etc. — so Streamlit pages only `SELECT` and plot, never compute. | Not started (Step 5) |

## Compute

| Resource | Use case | Status |
|---|---|---|
| **Cloud Run Job** `espn-ingest` | Runs once a day: builds an `espn-api` `League` object using the Secret Manager cookies, pulls all five data sources, and `MERGE`s them into BigQuery. Billed only for the seconds it actually runs — $0 the rest of the day. | Not started (Step 4) |
| **Cloud Run Service** (Streamlit dashboard) | Serves the 6-page dashboard to the league over one public-but-unlisted URL. `--min-instances 0` means it scales to zero between visits — no idle cost, just a short cold start on the next view. `--session-affinity` keeps each viewer pinned to one instance for Streamlit's websocket connection. | Not started (Step 7) |

## Scheduling

| Resource | Use case | Status |
|---|---|---|
| **Cloud Scheduler** job | Triggers `espn-ingest` automatically every day at 5:00 AM Arizona time (after that night's games have settled), so nobody has to remember to run it by hand. Falls inside the free tier (3 jobs/month free; this project needs 1). | Not started (Step 4) |

## Build and artifacts

| Resource | Use case | Status |
|---|---|---|
| **Cloud Build** | Builds the Docker images for both the ingest job and the dashboard directly from source — what `gcloud run jobs deploy --source` and `gcloud run deploy --source` do under the hood, no local Docker build required. | Used implicitly whenever Step 4/7's deploy commands run |
| **Artifact Registry** | Stores those built images between deploys. | Used implicitly, same as above |

## Observability

| Resource | Use case | Status |
|---|---|---|
| **Cloud Monitoring alert** on job failures | If ESPN returns a 401 (expired cookies) or the job otherwise fails, this is what notifies you to refresh the secret — without it, a silent ingest failure just means stale data with no warning. | Not started (Step 4) |

## CI/CD (deliberately deferred)

| Resource | Use case | Status |
|---|---|---|
| **Workload Identity Federation** + **GitHub Actions** | Lets GitHub Actions deploy to Cloud Run on push to `main` without a long-lived JSON service account key sitting in repo secrets. | Deliberately not set up yet — nothing deployable exists to test it against. Planned for right before Step 7's deploy, once `ingest/main.py` and the dashboard are real code instead of `NotImplementedError` stubs. |

## Cost summary

Every piece above that's actually built right now (project, budget, 2 service
accounts, 2 secrets, empty dataset) costs **$0/month**. Once the rest is built, the
architecture is designed to stay near-zero at idle too: Cloud Run scales to zero,
Cloud Scheduler and Secret Manager both fit their free tiers at this scale, and a
season of league data is well under BigQuery's free storage tier. See the proposal's
own [cost estimate](proposal.md#timeline-cost-and-risks) — under $1/month even fully
deployed.
