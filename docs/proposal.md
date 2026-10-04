# ESPN Fantasy Basketball Dashboard on GCP — Build Plan

This is the living Markdown version of the original build proposal PDF, kept in
version control so the plan can evolve with the project rather than staying frozen as
a static document. Where this diverges from the original PDF, it's marked explicitly
— see **Mock Trade Analysis** below, a feature added after the original proposal
(promoted out of that document's own stretch-goals list, with real UX detail the
original one-liner didn't have).

## Overview and goals

Build a hosted dashboard for a private ESPN fantasy basketball league, fed by a
scheduled pipeline on Google Cloud, in roughly 30–40 hours across 7 steps. The league
gets one link; data refreshes automatically; every view is backed by BigQuery history
ESPN itself doesn't keep.

The dashboard ships six features:

- **Category comparison** — any two teams side by side across the league's scoring
  categories (radar and bar charts)
- **Category power rankings** — teams ranked by category wins each week, not just
  W/L
- **Matchup breakdowns and luck analysis** — weekly results plus each team's record
  if it had played everyone
- **Trade and waiver tracking** — a running log of adds, drops, and trades
- **Roster strength by category** — where each roster is stacked or thin
- **Mock trade analysis** *(added after the original proposal)* — model the category
  impact of a hypothetical trade between two teams before proposing it for real

This plan assumes a head-to-head categories league with the standard 9 categories
(PTS, REB, AST, STL, BLK, 3PM, FG%, FT%, TO). A points league changes Steps 3 and 5
but nothing else.

## Architecture

Six GCP services plus GitHub: a scheduled job writes, BigQuery stores, and a Cloud
Run app reads.

```
Cloud Scheduler (daily 5:00 AM AZ trigger)
        │
        ▼
Cloud Run Job: espn-ingest  ──reads cookies──  Secret Manager (espn_s2, SWID)
        │
        │  pulls league data via the unofficial ESPN Fantasy API (espn-api)
        │  MERGEs into BigQuery
        ▼
BigQuery: fantasy dataset (5 raw tables + analytics views)
        │
        ▼
Cloud Run: Streamlit app (6 pages, cached queries)
        │
        ▼
League members (one public link, any device)
```

GitHub Actions deploys both Cloud Run services on push to `main`. Credentials never
leave the ingest side; the dashboard's service account can only read BigQuery.

## Step 1: Prerequisites (about 2 hours)

Set up the GCP project and grab the two ESPN cookies a private league needs.

1. Create a GCP project (e.g. `fantasy-hoops-dash`) and attach billing. Set a budget
   alert at $5/month so nothing surprises you.
2. Enable the APIs: Cloud Run, Cloud Scheduler, BigQuery, Secret Manager, Artifact
   Registry, Cloud Build.
3. Install the `gcloud` CLI locally and run `gcloud auth application-default login`
   so local code can reach BigQuery.
4. Create two service accounts with least-privilege roles:
   - `ingest-sa`: BigQuery Data Editor, BigQuery Job User, Secret Manager Secret
     Accessor
   - `dashboard-sa`: BigQuery Data Viewer, BigQuery Job User
5. Get your league ID from the ESPN league URL (`leagueId=` in the address bar).
6. Get the private-league cookies: log in to ESPN Fantasy in a desktop browser, open
   DevTools → Application → Cookies → `espn.com`, and copy `espn_s2` and `SWID`
   (keep the curly braces on `SWID`).
7. Create a GitHub repo with this layout:

   ```
   fantasy-dash/
     ingest/        # Cloud Run Job: ESPN → BigQuery
     sql/            # table DDL and analytics views
     app/             # Streamlit dashboard
     .github/workflows/
   ```

Treat the cookies like a password: they grant access to your ESPN account. Never
commit them; they go straight into Secret Manager in Step 4.

## Step 2: Local data access (about 3 hours)

Prove you can pull every dataset the six features need before touching the cloud.

```python
# pip install espn-api pandas
import os
from espn_api.basketball import League

league = League(
    league_id=int(os.environ["LEAGUE_ID"]),
    year=2027,  # ESPN labels the 2026-27 season by its ending year
    espn_s2=os.environ["ESPN_S2"],
    swid=os.environ["SWID"],
)

for team in league.teams:
    print(team.team_id, team.team_name, team.wins, team.losses)

box_scores = league.box_scores(matchup_period=1)  # per-category results
activity = league.recent_activity(size=50)          # adds, drops, trades
```

What each feature pulls:

| Feature | espn-api source |
|---|---|
| Category comparison | `league.box_scores()` category stats per team per matchup |
| Power rankings | `league.box_scores()` for every matchup period so far |
| Matchups and luck | `league.box_scores()` + `league.teams` |
| Trades and waivers | `league.recent_activity()` |
| Roster strength | `team.roster` and each player's `stats` |
| Mock trade analysis *(added)* | `team.roster` and each player's `stats` — same source as roster strength, no new pull |

**Done when:** a notebook prints a pandas DataFrame for each row above. Field names
shift between library versions, so inspect objects with `vars()` rather than
trusting docs.

## Step 3: BigQuery data model (about 3 hours)

One dataset, `fantasy`, with five raw tables; every row carries `season` and
`ingested_at` so history accumulates.

| Table | Grain | Key columns | Partition / cluster |
|---|---|---|---|
| `teams` | team × snapshot date | `team_id`, `team_name`, `owner`, `wins`, `losses`, `ties`, `standing` | partition `snapshot_date` |
| `matchup_categories` | matchup period × team × category | `matchup_period`, `team_id`, `opponent_id`, `category`, `value`, `result` (W/L/T) | cluster `matchup_period`, `team_id` |
| `rosters` | snapshot date × team × player | `team_id`, `player_id`, `player_name`, `position`, `lineup_slot`, `injury_status` | partition `snapshot_date` |
| `player_stats` | snapshot date × player × stat window | `player_id`, `window` (season, last 7, last 15, last 30), PTS, REB, AST, STL, BLK, 3PM, FGM, FGA, FTM, FTA, TO | partition `snapshot_date` |
| `transactions` | one row per action | `txn_id`, `txn_date`, `team_id`, `action` (ADD, DROP, TRADE), `player_id`, `player_name` | partition `txn_date` |

Two design choices matter:

- **Store makes and attempts, never just percentages.** FG% and FT% must be
  recomputed as `SUM(FGM) / SUM(FGA)`; averaging percentages gives wrong answers.
- **Long format for categories** (one row per category) keeps SQL views generic, so
  adding a 10th category is a config change, not a schema change.

Keep the DDL in `sql/ddl/` so the schema lives in version control.

No new tables for mock trade analysis — see the feature design below, which reuses
`rosters` and `player_stats` as-is.

## Step 4: Ingest job (about 6 hours)

A containerized Python script runs as a Cloud Run Job, reads cookies from Secret
Manager, and loads all five tables into BigQuery on a schedule.

1. Store the cookies:

   ```bash
   printf '%s' "$ESPN_S2" | gcloud secrets create espn-s2 --data-file=-
   printf '%s' "$SWID"    | gcloud secrets create espn-swid --data-file=-
   ```

2. Write `ingest/main.py`: build the `League` object, transform each source into a
   DataFrame, and load with `google-cloud-bigquery`.
3. Make every load idempotent. Load into a staging table, then `MERGE` into the
   target on its natural key (e.g. `matchup_period + team_id + category`). Re-runs
   then never duplicate rows.
4. Containerize with a slim `python:3.12-slim` Dockerfile and deploy:

   ```bash
   gcloud run jobs deploy espn-ingest \
     --source ingest/ --region us-west1 \
     --service-account ingest-sa@PROJECT.iam.gserviceaccount.com \
     --set-secrets ESPN_S2=espn-s2:latest,SWID=espn-swid:latest \
     --set-env-vars LEAGUE_ID=12345,SEASON=2027
   ```

5. Schedule it with Cloud Scheduler: daily at 5:00 AM Arizona time (after the
   night's games settle), plus an optional extra run Monday morning when matchups
   close.
6. Fail loudly: if ESPN returns a 401, the cookies expired. Log a clear error and
   set up a Cloud Monitoring alert on job failures so you know to refresh the
   secret.

**Done when:** a manual `gcloud run jobs execute espn-ingest` fills all five tables,
and running it twice changes no row counts.

## Step 5: Analytics layer (about 6 hours, +~1 hour for mock trade analysis)

Put all the logic in BigQuery views so the dashboard only selects and plots.

The core of all-play, in SQL:

| View | Feature | Logic |
|---|---|---|
| `v_team_week_cats` | Category comparison | Pivot `matchup_categories` to one row per team-week; recompute FG% and FT% from makes and attempts |
| `v_all_play` | Power rankings, luck | Self-join every team to every other team in the same week; count category wins in each simulated matchup |
| `v_power_rankings` | Power rankings | Season totals from `v_all_play`: all-play win %, category win %, rank |
| `v_luck` | Luck analysis | Actual win % minus all-play win %; positive means lucky |
| `v_transactions` | Trade and waiver tracking | Latest transactions with team names joined; counts per team |
| `v_roster_strength` | Roster strength | Sum each roster's per-game player stats (last 15 days); z-score each category across the league |
| `v_team_roster_stats` *(added)* | Mock trade analysis | Current roster joined to each player's per-game stat line (raw per-game averages, **not** z-scored — see below for why) |

```sql
SELECT a.matchup_period, a.team_id,
       COUNTIF(
         (a.category != 'TO' AND a.value > b.value) OR
         (a.category = 'TO' AND a.value < b.value)
       ) AS cat_wins
FROM matchup_categories a
JOIN matchup_categories b
  ON a.matchup_period = b.matchup_period
 AND a.category = b.category
 AND a.team_id != b.team_id
GROUP BY 1, 2
```

Turnovers are the one category where lower wins. Test every view against a week you
can verify by hand on ESPN.

**Why `v_team_roster_stats` isn't z-scored like `v_roster_strength`:** z-scores are
league-relative (how this roster compares to every other roster), which is the right
lens for "where is my team stacked or thin." A trade's impact is a before/after
comparison of two specific rosters' own raw totals — z-scoring would make "gained 3
rebounds a night" unreadable. Mock trade analysis needs the plain per-game numbers,
so it gets its own lightweight view rather than reusing `v_roster_strength` directly.

## Step 6: Streamlit dashboard (about 10 hours, +~5 hours for mock trade analysis)

A multipage Streamlit app with one page per feature, using Plotly for charts and
cached BigQuery reads.

Key implementation details:

- Wrap every query in `@st.cache_data(ttl=3600)` so page clicks don't rerun BigQuery
  queries. Data only changes once a day anyway.

| Page | Controls | Visuals |
|---|---|---|
| Compare | Pick two teams, week or season | Radar chart of category z-scores; side-by-side bars per category |
| Power Rankings | Week slider | Ranked table with all-play record; rank-over-time line chart |
| Matchups and Luck | Week picker | Category scoreboard per matchup; luck bar chart (actual vs all-play win %) |
| Transactions | Team filter, action filter | Activity log table; adds and drops per team bar chart |
| Roster Strength | Stat window (7, 15, 30 days) | Team × category heatmap of z-scores |
| Trade Analyzer *(added)* | Two team pickers, two player pickers | Before/after/delta category table, both sides — see feature design below |

- Keep one `queries.py` module that maps each page to its view; pages never contain
  raw SQL.
- Show a "last updated" timestamp from `MAX(ingested_at)` in the sidebar so the
  league trusts the numbers.
- Use the `st.navigation` pages API for the multipage layout and test on a phone,
  since most of the league will open it there.

**Done when:** all six pages run locally against BigQuery with
`streamlit run app/Home.py`.

### Feature design: Mock Trade Analysis *(added after the original proposal)*

**Goal:** model the category impact of a hypothetical trade between two teams,
before proposing it for real.

**UI flow:**

1. Two team pickers at the top of the page: **"Your team"** and **"Trade
   partner"** — both populated from `teams`; the trade-partner list excludes
   whichever team is picked as "yours."
2. Once both teams are chosen, two player pickers appear, one per team, each
   listing that team's current roster (from `v_team_roster_stats`) with every
   player's per-game stat line shown alongside their name — so you can see what
   you're trading without leaving the picker.
3. **Clicking a player's name moves them into the "selected to trade" section
   below** rather than just highlighting a dropdown row — selection is the action,
   not a separate "add" button. Clicking a selected player's name again removes
   them (toggle on/off).
4. Below the pickers, a section with two mirrored halves — **your side** and
   **your trade partner's side** — each showing:
   - the players that side is sending away (selected from their own roster)
   - the players that side is receiving (selected from the other roster)
   - that roster's category totals and per-game averages **before** the trade,
     **after** the trade, and the **delta** (gained or lost) per category

**Data needed:** no new ingest source and no new raw table — `rosters` and
`player_stats` (Step 3) already carry everything this needs. The one addition is
`v_team_roster_stats` (Step 5), a join of current roster to per-game stats, so the
app has one clean, already-joined source instead of assembling it from two raw
tables in Python every time a selection changes.

**Where the logic lives, and why this is the one exception to "logic belongs in
SQL":** every other page in this dashboard reads a precomputed view and just plots
it. Trade analysis can't work that way — which players are "sent" and "received" is
arbitrary and changes on every click, so there's nothing fixed to precompute. The
view supplies each roster's current player-level stats once; the
before/after/delta arithmetic (sum the selected players in, sum the selected
players out, recompute each roster's totals and averages) happens in the Streamlit
app itself, recalculated live as the selection changes. This is a deliberate,
named departure from the rest of the app's architecture, not an oversight.

**No persisted "your team":** like every other control in this app, team pickers
reset each session — there's no login and no per-user state (the whole dashboard is
one shared, unauthenticated link), so "your team" is just whichever team you
pick, same as any other page's filters.

## Step 7: Deploy and share (about 4 hours)

Deploy the Streamlit app as a Cloud Run service and give the league one URL.

```bash
gcloud run deploy fantasy-dash \
  --source app/ --region us-west1 \
  --service-account dashboard-sa@PROJECT.iam.gserviceaccount.com \
  --allow-unauthenticated --min-instances 0 --max-instances 2 \
  --session-affinity
```

- The Dockerfile runs `streamlit run Home.py --server.port=$PORT
  --server.address=0.0.0.0`. Cloud Run supports the websockets Streamlit uses;
  session affinity keeps each viewer on one instance.
- **Access:** `--allow-unauthenticated` makes the link public but unlisted. The
  dashboard holds no ESPN credentials, only league stats, so that's usually fine. If
  you want it locked down, add a simple shared password via `st.secrets`, or put
  Identity-Aware Proxy in front.
- **CI/CD:** a GitHub Actions workflow authenticates with Workload Identity
  Federation (no JSON keys) and redeploys the app on pushes to `main` that touch
  `app/`, and the job on pushes that touch `ingest/`.
- **Custom URL (optional):** map a domain you own with Cloud Run domain mapping or
  a load balancer.

**Done when:** someone in the league opens the link on their phone and sees today's
data.

## Timeline, cost, and risks

At about 8 hours a week, the original 7 steps ship in 4–5 weeks; costs should stay
under $1/month, inside GCP free tiers. Mock trade analysis adds roughly 6 hours on
top of that (≈1 hour in Step 5, ≈5 hours in Step 6, mostly the interactive
add/remove-and-recompute logic) — call it 4–6 weeks at the same pace.

**Cost:** BigQuery stores well under 1 GB and queries far under the 1 TB/month free
tier. Cloud Run, Scheduler (3 free jobs), and Secret Manager all fit their free
tiers at league scale. The budget alert from Step 1 is the backstop.

| Risk | Impact | Mitigation |
|---|---|---|
| ESPN cookies expire | Ingest fails with 401 | Failure alert; add a new secret version, no redeploy needed |
| ESPN changes its unofficial API | Ingest breaks | Pin the `espn-api` version; raw tables keep history even if a run fails |
| Library fields differ by version | Wrong or missing columns | Validate DataFrame columns before loading; fail the run on mismatch |
| Percentage categories miscomputed | Wrong rankings | Store makes and attempts; recompute in SQL |
| Cold starts | First page load takes a few seconds | Accept it, or set min instances to 1 (adds cost) |

## Stretch goals

Once the core ships (now including mock trade analysis, promoted out of this list):
a dbt project for the views, playoff odds via Monte Carlo simulation, and a weekly
recap posted to the league's group chat.
