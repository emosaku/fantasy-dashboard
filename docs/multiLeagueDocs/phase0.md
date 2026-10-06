# League Lab — Phase 0: Foundation

**Status: done (October 5, 2026).** Phase 0 gives League Lab its own home and makes
sure it can't run up a bill or be hard to switch off. Nothing user-facing ships in
this phase.

## 1. Its own Google Cloud project

| | |
|---|---|
| Project | `league-lab-emk` (project number 653265430384), billed to Eni's Billing |
| Region | `us-west1` for everything (Cloud Run, BigQuery dataset `league_lab`, Scheduler) |
| Firestore | Native mode, `(default)` database — the league registry, users and memberships |
| Why separate | The original league's site (`fantasy-dash-emk`, branch `main`) is for friends and stays untouched. A separate project has its own budget, kill switch and IAM, and teardown can delete the whole project without touching it. |

### Service accounts (least privilege)

| Account | Runs | Can do |
|---|---|---|
| `ingest-sa` | Cloud Run Job `league-ingest` | Run BigQuery jobs; edit the `league_lab` dataset; read/write Firestore; manage only secrets named `league-*` (an IAM condition) |
| `dashboard-sa` | Cloud Run service `league-lab` | Run BigQuery jobs; **read** the `league_lab` dataset; read/write Firestore; start `league-ingest` with overrides (refresh, first load, purge) |
| `killswitch-sa` | Cloud Run function `killswitch` | Custom role `killSwitch`: list and pause Scheduler jobs, read and change Cloud Run access policies. Nothing else. |

## 2. Cost guardrails and the kill switch

| Guardrail | Setting |
|---|---|
| Budget | $5/month on this project; emails at 50/90/100% |
| Kill switch | At 100%: pauses every Scheduler job and removes public access from every Cloud Run service (the new `league-lab` service included — it lists all services) |
| BigQuery cap | 30 GiB of queries per day; past it, queries fail instead of costing money |
| Ingest alert | "League Lab ingest failed" emails when any `league-ingest` task fails |

Full runbook, tests and how to re-open the site after it trips:
[killswitch.md](killswitch.md).

## 3. Config, not constants

Nothing in the League Lab code names a project. The dashboard reads its settings
from the environment (`app/settings.py`); the ingest job from `ingest/main.py`'s
`Config`:

| Variable | Used by | Default |
|---|---|---|
| `GCP_PROJECT_ID` | both | — (required) |
| `BIGQUERY_DATASET` / `BIGQUERY_LOCATION` | both | `league_lab` / `us-west1` |
| `GCP_REGION`, `INGEST_JOB` | dashboard (to start the job) | `us-west1`, `league-ingest` |
| `SEASON` | both | `2027` (ESPN names a season by the year it ends) |
| `MAX_LEAGUES`, `MAX_LEAGUES_PER_USER` | dashboard | 10, 3 |
| `SHUTDOWN` | dashboard | off; `1` shows the shutdown page |
| `DEV_AUTH_EMAIL` | dashboard, **local only** | off; ignored on Cloud Run |
| `LEAGUE_IDS`, `PURGE_ONLY` | ingest | off; set per run by the dashboard |

The SQL is templated too: `sql/ddl` and `sql/views` use `{project}` and `{dataset}`,
and `scripts/apply_sql.py --project league-lab-emk --dataset league_lab` creates the
dataset, tables, views and precomputed tables.

## Checks

- Kill switch unit-tested (`tests/ops/`) and tested live with a fake budget message.
- CI runs lint, format and the whole test suite (now 93 tests) on every push.
