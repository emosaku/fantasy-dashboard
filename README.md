# League Lab

> **Branch `multi-league`.** This branch turns the single-league dashboard into
> **League Lab**: the same analysis for any public ESPN head-to-head categories
> fantasy basketball league, with Google sign-in, invite links, per-league data and
> near-zero running cost. It's a separate site in its own Google Cloud project
> (`league-lab-emk`). The original league's site stays on `main`, untouched; branch
> `InitialSingleLeagueBuild` is a snapshot of `main` from before this work began.

## What it does

A commissioner signs in with Google, registers a public league from its ESPN link,
and shares an invite link; members join and claim their team. Every league gets:

- **Compare**: any two teams, category by category, for a week or the season
- **Power Rankings**: all-play rankings, plus an injury-aware projected finish
- **Matchups and Luck**: every scoreboard, and who's winning more than their stats say
- **Transactions**: every add, drop, trade and lineup move, filterable
- **Roster Strength**: every team ranked in every category, with Lock / Swing / Punt tiers
- **Trade Analyzer**: waiver moves and win-win trades for your own team, and a mock trade
- **Player Rankings**: every player ranked in every category and overall

Scoring rules are read from each league: any category set (turnovers count lower-is-
better; FG%, FT%, 3PT% and A/TO are ratios), Most Categories or Each Category.

## Docs

| | |
|---|---|
| [docs/multiLeagueDocs/plan.md](docs/multiLeagueDocs/plan.md) | Decisions and the phased plan |
| [docs/multiLeagueDocs/phase0.md](docs/multiLeagueDocs/phase0.md) | Phase 0: the project, guardrails, config |
| [docs/multiLeagueDocs/killswitch.md](docs/multiLeagueDocs/killswitch.md) | Budget kill switch runbook |
| [docs/multiLeagueDocs/phase1.md](docs/multiLeagueDocs/phase1.md) | Phase 1: tenancy, generic scoring, ingest fan-out, sign-in, ops, load test, cost, what's left |
| [docs/initialSingleLeagueBuildDocs/](docs/initialSingleLeagueBuildDocs/) | The original single-league build |

## Architecture

```
Browser ──Google sign-in──▶ Cloud Run `league-lab` (Streamlit) ──▶ Firestore (users, leagues, members)
                                    │ reads m_* tables for one league
Cloud Scheduler (daily) ──▶ Cloud Run Job `league-ingest` (parallel tasks) ──▶ ESPN (public leagues)
                                    ▼
                     BigQuery `league_lab`: raw tables ─▶ views ─▶ m_* tables
Budget $5/month ──▶ Pub/Sub ──▶ `killswitch` function (pauses schedule, closes site)
```

## Setup (local)

Requires Python 3.12+ and `gcloud auth application-default login` with access to
`league-lab-emk`.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env   # GCP_PROJECT_ID=league-lab-emk, and DEV_AUTH_EMAIL=<you> to
                       # sign in locally without Google (ignored on Cloud Run)
streamlit run app/Home.py   # from the repo root
pytest
```

## Project layout

```
├── app/                    # Streamlit dashboard
│   ├── Home.py               # sign-in gate, navigation, league switcher, standings
│   ├── pages/                # 7 analysis pages + register, join, league settings, privacy
│   ├── settings.py           # environment config
│   ├── league.py             # who's signed in, which league, its rules (from Firestore)
│   ├── tenancy.py            # registry rules: register, invite, join, delete, refresh limit
│   ├── onboarding.py         # registration checks against ESPN
│   ├── queries.py            # every BigQuery read (m_* tables, one league per query)
│   ├── refresh.py            # starts the ingest job (refresh, first load, purge)
│   ├── categories.py         # generic categories: counts, ratios, direction, formatting
│   ├── analysis/             # trade/waiver analyzer, rankings, projection (pure, tested)
│   └── analyzer.py, compare.py, trade.py, ui.py
├── ingest/                 # Cloud Run Job: ESPN -> BigQuery, per league, fanned out
│   ├── main.py, registry.py, catalog.py, espn_client.py, transform.py,
│   └── bigquery_load.py, materialize.py, credentials.py
├── sql/ddl, sql/views      # templated with {project}/{dataset}
├── ops/killswitch/         # budget kill switch (Cloud Run function)
├── scripts/                # apply_sql.py, teardown.py, load_test.py
├── tests/                  # app, ingest, ops; fixtures (4-team league, fake Firestore)
└── docs/
```

Never committed: `.env`, `.streamlit/secrets.toml` (sign-in settings).

League Lab is not affiliated with, endorsed by or sponsored by ESPN or the NBA.
