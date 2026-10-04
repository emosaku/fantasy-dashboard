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
| 1 | Prerequisites — GCP project, APIs, service accounts, league ID, ESPN cookies | Not started |
| 2 | Local data access — prove `espn-api` can pull every dataset the 5 features need | Not started |
| 3 | BigQuery data model — 5 raw tables (long format, makes/attempts not percentages) | Not started |
| 4 | Ingest job — containerized Cloud Run Job, staging + `MERGE` for idempotency | Not started |
| 5 | Analytics layer — BigQuery views (all-play, power rankings, luck, roster strength, team roster stats) | Not started |
| 6 | Streamlit dashboard — 6 pages, cached queries, phone-friendly | Not started |
| 7 | Deploy and share — Cloud Run service, CI/CD, one link for the league | Not started |

## Current state

**This is scaffolding only.** The repository layout mirrors the plan above —
`ingest/`, `sql/{ddl,views}/`, `app/{,pages}/`, `.github/workflows/` — with every file
a placeholder describing what it will hold and which step builds it. Nothing queries
ESPN, nothing touches BigQuery, and nothing is deployed yet.

- `ingest/main.py` — Cloud Run Job entry point (Step 4), currently
  `raise NotImplementedError`
- `sql/ddl/*.sql`, `sql/views/*.sql` — one file per table/view named in the proposal
  (Steps 3 & 5), currently comment-only
- `app/Home.py`, `app/pages/*.py`, `app/queries.py` — Streamlit entry point, the 6
  feature pages, and the page-to-view mapping module (Step 6), currently docstring-only
- `.github/workflows/deploy-{ingest,app}.yml` — valid but `workflow_dispatch`-only
  (manual trigger), so they can't fire on push before Step 7 actually wires them up
- `tests/` mirrors `ingest/` and `app/` with one placeholder test each, so `pytest`
  has something to discover

## Setup

Requires Python 3.12+.

```bash
python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt -r requirements-dev.txt

cp .env.example .env   # fill in later -- nothing needs real values yet

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
  Build — none provisioned yet (Step 1)

## Project layout

```
FantasyDashboard/
├── ingest/                  # Step 4: Cloud Run Job, ESPN -> BigQuery
│   └── main.py
├── sql/
│   ├── ddl/                  # Step 3: table definitions (5 raw tables)
│   └── views/                 # Step 5: analytics views (7 views)
├── app/                        # Step 6: Streamlit dashboard
│   ├── Home.py
│   ├── pages/                   # one file per feature (6 pages)
│   └── queries.py                 # page -> view mapping, no raw SQL in pages
├── tests/                          # mirrors ingest/ and app/
├── .github/workflows/                # Step 7: CI/CD, manual-trigger stubs for now
├── docs/                               # design notes, including proposal.md (the full plan)
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml                        # ruff + pytest config only (no installable package)
├── .env.example
└── README.md
```
