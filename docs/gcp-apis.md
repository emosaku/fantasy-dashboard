# GCP APIs enabled on `fantasy-dash-emk`

Step 1 of [`proposal.md`](proposal.md) calls for enabling six APIs on the project
before any infrastructure gets built. This records what each one is for, so the
reasoning behind Step 1 doesn't just live in a shell command.

| API | Enables | Used for |
|---|---|---|
| `run.googleapis.com` | Cloud Run | Hosts the `espn-ingest` container as a Cloud Run **Job** (Step 4) and the Streamlit dashboard as a Cloud Run **Service** (Step 7). |
| `cloudscheduler.googleapis.com` | Cloud Scheduler | Triggers `espn-ingest` automatically on a daily schedule (5:00 AM AZ, after that night's games settle), instead of running it by hand. |
| `bigquery.googleapis.com` | BigQuery | The project's database — the five raw tables (`teams`, `matchup_categories`, `rosters`, `player_stats`, `transactions`) and every analytics view (Step 3, Step 5). |
| `secretmanager.googleapis.com` | Secret Manager | Holds the ESPN `espn_s2`/`SWID` session cookies outside the repo; Cloud Run injects them into `espn-ingest` as env vars at runtime (Step 4). |
| `artifactregistry.googleapis.com` | Artifact Registry | Stores the Docker images built for `espn-ingest` and the dashboard. |
| `cloudbuild.googleapis.com` | Cloud Build | Builds those images from source — what `gcloud run jobs deploy --source` and `gcloud run deploy --source` use under the hood. |

## Why these six and not others

Enabling `bigquery.googleapis.com` and `run.googleapis.com` auto-enables several
related APIs alongside them (the full BigQuery family, logging/monitoring, Cloud
Storage, IAM, etc.) — that's normal GCP dependency behavior, not something this
project configured. Those extra APIs cost nothing by themselves and need no
separate setup; this list only covers the six the proposal actually calls for and
that later steps directly depend on.

## Where each gets used

- Step 4 (ingest job): `run.googleapis.com`, `cloudscheduler.googleapis.com`,
  `secretmanager.googleapis.com`, `artifactregistry.googleapis.com`,
  `cloudbuild.googleapis.com`, `bigquery.googleapis.com`
- Step 5 (analytics views): `bigquery.googleapis.com`
- Step 7 (dashboard deploy): `run.googleapis.com`, `artifactregistry.googleapis.com`,
  `cloudbuild.googleapis.com`
