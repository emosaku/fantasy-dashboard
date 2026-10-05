# Fantasy Basketball Dashboard

## Overview

A dashboard for a private 14-team ESPN fantasy basketball league, fed by a daily
pipeline on Google Cloud. Each manager signs in with their own login; data refreshes
automatically every morning (or on demand); every view is backed by BigQuery history
ESPN itself doesn't keep (ESPN's own UI doesn't retain all-play records, category
breakdowns over time, or a queryable activity log).

The league is head-to-head **Most Categories** with 9 categories: FG%, FT%, 3PM, 3PT%,
REB, AST, STL, BLK, PTS (no turnovers), and a 16-week regular season.

What the dashboard does:

- **Compare** — any two teams, category by category, for a week or the season
- **Power Rankings** — all-play rankings (your record if you'd played everyone every
  week), plus an injury-aware projected finish through the end of the regular season
- **Matchups and Luck** — every week's scoreboards, and who's winning more (or less)
  than their stats say
- **Transactions** — every add, drop, trade and lineup move, filterable by date, team,
  action and player
- **Roster Strength** — category rankings 1-14 for every team (roster strength or
  actual results), with Lock / Swing / Punt tiers, and per-game totals
- **Trade Analyzer** — for the signed-in manager's team: waiver pickups and win-win
  trades ranked by category wins gained, with plain-text explanations, and a mock-trade
  simulator showing health and games-played history for every player in the deal

The original build plan, and every feature added since, lives in
[`docs/proposal.md`](docs/proposal.md).

## Architecture

```
Cloud Scheduler (daily, 5 AM Arizona)      "Refresh data" button (on demand)
        │                                          │
        ▼                                          ▼
Cloud Run Job: espn-ingest  ──reads cookies──  Secret Manager (espn_s2, SWID)
        │
        │  ESPN Fantasy API (espn-api + ESPN's raw feeds for activity and player info)
        ▼
BigQuery: fantasy dataset (9 raw tables + 12 analytics views)
        │
        ▼
Streamlit app (7 pages, cached BigQuery reads, manager logins) -- Cloud Run in Step 7
        │
        ▼
League managers (one link, any device, own username and password)
```

Credentials never leave the ingest side — `ingest-sa` can write BigQuery and read the
ESPN secrets; `dashboard-sa` (the dashboard's identity) reads BigQuery and, from Step 7,
can trigger the ingest job for the Refresh button. GitHub Actions will redeploy both
on push to `main` via Workload Identity Federation (no JSON keys).

## Step roadmap

| Step | Description | Status |
|---|---|---|
| 0 | Project scaffolding, tooling, environment | **Complete** |
| 1 | Prerequisites — GCP project, APIs, service accounts, league ID, ESPN cookies | **Complete** |
| 2 | Local data access — prove `espn-api` can pull every dataset the features need | **Complete** |
| 3 | BigQuery data model — raw tables (long format, makes/attempts not percentages) | **Complete** |
| 4 | Ingest job — containerized Cloud Run Job, staging + `MERGE` for idempotency | **Complete** |
| 5 | Analytics layer — BigQuery views (all-play, rankings, luck, z-scores, category ranks) | **Complete** |
| 6 | Streamlit dashboard — 7 pages, logins, recommendations, phone-friendly | **Complete** (local) |
| 7 | Deploy and share — Cloud Run service, CI/CD, one link for the league | Not started |

## Current state

Steps 1-6 are real: the GCP project, BigQuery tables and views, and the ingest job
are deployed and running, and the dashboard runs locally against live BigQuery
(`streamlit run app/Home.py` from the repo root). Step 7 (deploying the dashboard,
CI/CD) is next; see [`docs/step7-deploy.md`](docs/step7-deploy.md).

- `fantasy-dash-emk` is a real GCP project — billing linked, $5/month budget alert,
  the required APIs enabled. `ingest-sa`/`dashboard-sa` service accounts exist with
  least-privilege IAM; `espn-s2`/`espn-swid` live in Secret Manager.
- The `fantasy` BigQuery dataset has 9 raw tables (`sql/ddl/*.sql`): `teams`,
  `matchup_categories`, `rosters`, `player_stats`, `transactions`, `free_agents`,
  `league_status`, `player_seasons`, `player_details` — all filled from the live league.
- `ingest/` is a deployed Cloud Run Job (`espn-ingest`). Each run pulls the league from
  ESPN and `MERGE`s it into BigQuery; same-day snapshots are replaced, never duplicated.
  Cloud Scheduler (`espn-ingest-daily`, 5 AM `America/Phoenix`) runs it daily and a
  Cloud Monitoring alert fires on failures. See
  [`docs/step4-ingest.md`](docs/step4-ingest.md).
- `sql/views/*.sql` — 12 analytics views, live in the `fantasy` dataset. See
  [`docs/step5-analytics.md`](docs/step5-analytics.md).
- `app/` — the Streamlit dashboard, behind manager logins created with
  `python scripts/manage_logins.py`. See [`docs/step6-dashboard.md`](docs/step6-dashboard.md).
- `tests/` — 61 tests: the ingest transforms and MERGE statement, the dashboard's math,
  the trade/waiver analyzer (on a synthetic 4-team league), the season projection,
  logins, and the refresh button.
- `.github/workflows/deploy-{ingest,app}.yml` — valid but `workflow_dispatch`-only
  until Step 7.

## Setup

Requires Python 3.12+.

```bash
python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt -r requirements-dev.txt

cp .env.example .env   # fill in LEAGUE_ID/SEASON/ESPN_S2/SWID/GCP_PROJECT_ID
gcloud auth application-default login   # BigQuery and the Refresh button use this

python scripts/manage_logins.py   # once: creates the manager logins
streamlit run app/Home.py         # from the repo root
pytest
```

## Tech stack

- Python 3.12+
- `espn-api`, `requests`, `pandas` — pulling and shaping league data
- `google-cloud-bigquery` — loading and querying
- `streamlit`, `plotly`, `numpy` — the dashboard and its analysis
- `python-dotenv` — local env var loading
- `pytest`, `ruff` — testing and linting
- GCP: Cloud Run, Cloud Scheduler, BigQuery, Secret Manager, Artifact Registry, Cloud
  Build, Cloud Monitoring — see [`docs/gcp-services.md`](docs/gcp-services.md)

## Project layout

```
FantasyDashboard/
├── ingest/                    # Cloud Run Job: ESPN -> BigQuery (deployed)
│   ├── main.py                  # pulls every source, MERGEs each table
│   ├── espn_client.py           # espn_api League + raw ESPN player-info fetch (any season)
│   ├── transform.py             # ESPN objects/records -> DataFrames matching sql/ddl/
│   ├── bigquery_load.py         # staging table + MERGE; daily snapshots replaced in full
│   ├── Dockerfile
│   └── requirements.txt         # lean subset for the deployed image
├── sql/
│   ├── ddl/                     # 9 raw tables (live in BigQuery)
│   └── views/                   # 12 analytics views (live in BigQuery)
├── app/                         # Streamlit dashboard
│   ├── Home.py                  # login gate, navigation, standings
│   ├── pages/                   # the 6 feature pages
│   ├── queries.py               # the only place SQL lives; every read cached 1 hour
│   ├── analysis/                # trade/waiver analyzer + season projection (pure, tested)
│   ├── analyzer.py              # cached glue between the views and analysis/
│   ├── auth.py, login.py        # password hashing + lockout; login page and session
│   ├── refresh.py               # the Refresh data button (runs the ingest job)
│   ├── categories.py, compare.py, trade.py, ui.py
├── scripts/manage_logins.py     # create / reset manager logins
├── notebooks/                   # Step 2: one-off ESPN API exploration
├── tests/                       # mirrors ingest/ and app/; fixtures/ holds the 4-team league
├── .github/workflows/           # Step 7: CI/CD, manual-trigger stubs for now
├── docs/                        # proposal.md (the plan), step4-7 docs, gcp-apis.md,
│                                  gcp-services.md
├── requirements.txt, requirements-dev.txt
├── pyproject.toml               # ruff + pytest config only
├── .env.example
└── README.md
```

Git-ignored and never committed: `.env` (ESPN cookies), `.streamlit/secrets.toml`
(login password hashes) and `manager-logins.csv` (plain passwords to hand out).
