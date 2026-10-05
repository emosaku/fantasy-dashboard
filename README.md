# Fantasy Basketball Dashboard

## Overview

A hosted dashboard for a private ESPN fantasy basketball league, fed by a scheduled
pipeline on Google Cloud. The league gets one link; data refreshes automatically once
a day; every view is backed by BigQuery history ESPN itself doesn't keep (ESPN's own
UI doesn't retain season-over-season category breakdowns, all-play records, or a
queryable transaction log).

Six features, once built:

- **Category comparison** — any two teams side by side across all 9 scoring
  categories
- **Category power rankings** — teams ranked by category wins each week, not just
  win/loss record
- **Matchup breakdowns and luck analysis** — weekly results plus each team's record
  if it had played every other team that week ("all-play")
- **Trade and waiver tracking** — a running log of adds, drops, and trades
- **Roster strength by category** — where each roster is stacked or thin, by
  category
- **Mock trade analysis** *(added after the original proposal)* — pick two teams
  and players from each roster to see both sides' category totals before, after,
  and the delta — model a trade before proposing it for real

This assumes a head-to-head categories league with the standard 9 categories (PTS,
REB, AST, STL, BLK, 3PM, FG%, FT%, TO). The full plan, including the original build
proposal and this feature's design, lives in
[`docs/proposal.md`](docs/proposal.md).

## Architecture

```
Cloud Scheduler (daily trigger)
        │
        ▼
Cloud Run Job: espn-ingest  ──reads cookies──  Secret Manager (espn_s2, SWID)
        │
        │  pulls league data via the unofficial ESPN Fantasy API (espn-api)
        ▼
BigQuery: fantasy dataset (5 raw tables, partitioned/clustered + analytics views)
        │
        ▼
Cloud Run: Streamlit app (6 pages, cached BigQuery reads)
        │
        ▼
League members (one public-but-unlisted link, any device)
```

Credentials never leave the ingest side — `ingest-sa` can write BigQuery and read
secrets; `dashboard-sa` (the Streamlit app's identity) can only read BigQuery. GitHub
Actions redeploys both Cloud Run services on push to `main`, authenticating via
Workload Identity Federation (no JSON keys).

## Step roadmap

| Step | Description | Status |
|---|---|---|
| 0 | Project scaffolding, tooling, environment | **Complete** |
| 1 | Prerequisites — GCP project, APIs, service accounts, league ID, ESPN cookies | **Complete** |
| 2 | Local data access — prove `espn-api` can pull every dataset the 5 features need | **Complete** |
| 3 | BigQuery data model — 5 raw tables (long format, makes/attempts not percentages) | **Complete** |
| 4 | Ingest job — containerized Cloud Run Job, staging + `MERGE` for idempotency | **Complete** |
| 5 | Analytics layer — BigQuery views (all-play, power rankings, luck, roster strength, team roster stats) | **Complete** |
| 6 | Streamlit dashboard — 6 pages, cached queries, phone-friendly | Not started |
| 7 | Deploy and share — Cloud Run service, CI/CD, one link for the league | Not started |

## Current state

Steps 1-5 are real and live, not scaffolding: the GCP project, BigQuery tables, the
ingest job, and the analytics views are all deployed and running. Steps 6-7
(dashboard, CI/CD) are still scaffolding.

- `fantasy-dash-emk` is a real GCP project — billing linked, $5/month budget alert,
  the 6 required APIs enabled. `ingest-sa`/`dashboard-sa` service accounts exist with
  least-privilege IAM; `espn-s2`/`espn-swid` live in Secret Manager.
- The `fantasy` BigQuery dataset has all 5 raw tables (`sql/ddl/*.sql`), populated
  with real data from the user's live ESPN league.
- `ingest/` is a real, deployed Cloud Run Job (`espn-ingest`) — pulls all 5 data
  sources from ESPN and `MERGE`s them into BigQuery. Verified idempotent against the
  live deployment (same row counts across 3 real executions, including one via Cloud
  Scheduler). See [`docs/step4-ingest.md`](docs/step4-ingest.md) for the real bugs
  this surfaced and how they were fixed.
- Cloud Scheduler (`espn-ingest-daily`, 5 AM `America/Phoenix`) and a Cloud Monitoring
  alert on job failures are both live.
- `sql/views/*.sql` — all 7 analytics views, live in the `fantasy` dataset. See
  [`docs/step5-analytics.md`](docs/step5-analytics.md) for what each one computes
  and how they were verified.
- `app/Home.py`, `app/pages/*.py`, `app/queries.py` — Streamlit entry point, the 6
  feature pages, and the page-to-view mapping module (Step 6), currently docstring-only
- `.github/workflows/deploy-{ingest,app}.yml` — valid but `workflow_dispatch`-only
  (manual trigger), deliberately deferred until Step 7 — no point wiring up CI/CD
  before the dashboard exists to deploy
- `tests/ingest/test_transform.py` covers the ingest job's transform logic (home/away
  unpacking, stat-window selection, transaction flattening); `tests/app/` still has
  its placeholder, pending Step 6

## Setup

Requires Python 3.12+.

```bash
python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt -r requirements-dev.txt

cp .env.example .env   # fill in LEAGUE_ID/SEASON/ESPN_S2/SWID/GCP_PROJECT_ID to run ingest locally

pytest
```

## Tech stack

- Python 3.12+
- `espn-api`, `pandas` — pulling and shaping league data (Step 2)
- `google-cloud-bigquery` — loading and querying (Steps 3-5)
- `streamlit`, `plotly` — the dashboard (Step 6)
- `python-dotenv` — local env var loading
- `pytest`, `ruff` — testing and linting
- GCP: Cloud Run, Cloud Scheduler, BigQuery, Secret Manager, Artifact Registry, Cloud
  Build — all provisioned on `fantasy-dash-emk` (Step 1); see
  [`docs/gcp-services.md`](docs/gcp-services.md)

## Project layout

```
FantasyDashboard/
├── ingest/                  # Step 4: Cloud Run Job, ESPN -> BigQuery -- deployed
│   ├── main.py                # orchestrates the 5 transform+load calls
│   ├── espn_client.py            # builds the espn_api League from env vars
│   ├── transform.py                # espn-api objects -> DataFrames matching sql/ddl/
│   ├── bigquery_load.py              # staging table + MERGE, idempotent load
│   ├── Dockerfile                      # build context for --source ingest/
│   └── requirements.txt                  # lean subset for the deployed image
├── sql/
│   ├── ddl/                  # Step 3: table definitions (5 raw tables) -- live in BigQuery
│   └── views/                 # Step 5: analytics views (7 views)
├── app/                        # Step 6: Streamlit dashboard
│   ├── Home.py
│   ├── pages/                   # one file per feature (6 pages)
│   └── queries.py                 # page -> view mapping, no raw SQL in pages
├── notebooks/                       # Step 2: one-off ESPN API exploration
├── tests/                          # mirrors ingest/ and app/
├── .github/workflows/                # Step 7: CI/CD, manual-trigger stubs for now
├── docs/                               # proposal.md (the full plan), gcp-apis.md,
│                                          gcp-services.md, step4-ingest.md
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml                        # ruff + pytest config only (no installable package)
├── .env.example
└── README.md
```
