# Step 4: Ingest job

Step 3 built the five empty BigQuery tables. Step 4 is what fills them — a
containerized Python job that pulls the league from ESPN and loads it into
BigQuery on a schedule. This is the one piece of the whole project that actually
talks to ESPN; everything downstream (views, dashboard) only ever reads BigQuery.

## What already exists for this step

- `ingest-sa@fantasy-dash-emk.iam.gserviceaccount.com` — BigQuery Data Editor, BigQuery
  Job User, Secret Manager Secret Accessor (created in Step 1)
- `espn-s2` / `espn-swid` secrets in Secret Manager (created in Step 1)
- The five live tables in the `fantasy` dataset, each with its natural key documented
  in `sql/ddl/*.sql` (created in Step 3) — Step 4's `MERGE` statements key off these
  exactly
- `notebooks/01_explore_espn_api.py` — proved the real `espn-api` object shapes
  against the live league (Step 2); Step 4's transform logic is built directly on
  what that script found, not on the library's docs

What's missing is the actual job: `ingest/main.py` still just
`raise NotImplementedError`.

## The job, end to end

```
Cloud Scheduler (5:00 AM AZ, daily)
        │ triggers
        ▼
Cloud Run Job: espn-ingest
        │ 1. reads ESPN_S2/SWID from Secret Manager (injected as env vars)
        │ 2. builds espn_api.basketball.League
        │ 3. pulls 5 sources, transforms each to a DataFrame
        │ 4. loads each into a staging table, then MERGEs into the real table
        ▼
BigQuery: fantasy.{teams, matchup_categories, rosters, player_stats, transactions}
```

## Transform logic per table

This is the real engineering work in this step — turning each `espn-api` object's
actual (not documented) shape into the flat rows each table expects.

### `teams`
Straightforward — one row per team per ingest run. `league.teams` already gives
`team_id`, `team_name`, `wins`, `losses`, `standing` directly as flat attributes.

### `matchup_categories`
**Not straightforward.** `league.box_scores(matchup_period=N)` returns one object
*per matchup*, with `home_team`/`away_team` and `home_stats`/`away_stats` dicts
(each category → `{value, result}`) — not one row per team. The transform has to
unpack every matchup into **two** rows, one for the home side and one for the away
side, each getting its own `team_id`/`opponent_id`. Loop over every category in
`home_stats`/`away_stats` for both sides, for every matchup period played so far.

### `rosters`
`team.roster` is a flat list of `Player` objects — straightforward. One row per
player per team per run, pulling `player_id`, `player_name` (`.name`),
`position` (`.position`), `lineup_slot`, `injury_status` directly.

### `player_stats`
**The trickiest source.** `Player.stats` is a dict keyed by window
(`'2027_total'`, `'2027_last_30'`, `'2027_last_15'`, `'2027_last_7'`,
`'2027_projected'`), and only `'_projected'`/`'_total'` carry a nested `avg`/`total`
sub-dict with the real per-category breakdown — `'_last_7/15/30'` are all zero right
now because the season hasn't started. The transform:
1. Iterates the known window suffixes, stripping the season prefix to get
   `stat_window` ('season', 'last_7', 'last_15', 'last_30', 'projected' — mapped
   from ESPN's `_total`/`_last_N`/`_projected` keys)
2. Pulls the per-category numbers from the nested `avg` sub-dict (per-game
   averages, so windows of different lengths stay comparable)
3. Writes a row even when a window's numbers are all zero (that's real information —
   it means no games have been played in that window yet) **except** it always
   includes `'projected'`, since that's the one window with real non-zero numbers
   before the season starts

### `transactions`
`league.recent_activity(size=N)` returns one entry per timestamp, and each entry's
`actions` field is a **list** of `(team, action_string, player_name, _)` tuples — a
single trade can bundle several player moves under one timestamp. The transform
flattens this: one output row per tuple, not per `recent_activity()` entry. Since
ESPN provides no stable transaction id, `txn_id` is synthesized as a deterministic
hash of `(txn_date, team_id, action, player_id)` — deterministic so re-running
ingest produces the same `txn_id` for the same action, which is what makes the
`MERGE` idempotent for this table specifically.

## Idempotency: staging table + MERGE

Every table follows the same pattern, so re-running the job (intentionally, or
because Cloud Scheduler fires twice) never duplicates rows:

1. Load the day's transformed DataFrame into a `_staging` table (overwrite each run)
2. `MERGE` the target table against staging, matching on that table's natural key
   (documented in each `sql/ddl/*.sql` file's header comment)
3. On match: update the row (handles corrections, e.g. a late stat update). On no
   match: insert.

```sql
MERGE fantasy.matchup_categories T
USING fantasy.matchup_categories_staging S
ON T.season = S.season
   AND T.matchup_period = S.matchup_period
   AND T.team_id = S.team_id
   AND T.category = S.category
WHEN MATCHED THEN UPDATE SET T.value = S.value, T.result = S.result, T.ingested_at = S.ingested_at
WHEN NOT MATCHED THEN INSERT ROW
```

## Containerize and deploy

A slim `python:3.12-slim` image, built and deployed straight from source (Cloud
Build + Artifact Registry handle the build, no local Docker needed):

```bash
gcloud run jobs deploy espn-ingest \
  --source ingest/ --region us-west1 \
  --service-account ingest-sa@fantasy-dash-emk.iam.gserviceaccount.com \
  --set-secrets ESPN_S2=espn-s2:latest,SWID=espn-swid:latest \
  --set-env-vars LEAGUE_ID=383633368,SEASON=2027
```

Cookies come from Secret Manager at runtime — never baked into the image, never
read from `.env` (that file only exists for local development).

## Scheduling and failure handling

- **Cloud Scheduler**: triggers the job daily at 5:00 AM Arizona time, after that
  night's games have settled (plus, optionally, an extra Monday-morning run when
  weekly matchups close).
- **Fail loudly**: a 401 from ESPN means the cookies expired, not a code bug — log
  it distinctly from other failures. A Cloud Monitoring alert on job failures means
  a silent ingest failure doesn't just become stale data with no warning.

## Done when

A manual `gcloud run jobs execute espn-ingest` fills all five tables, and running it
a second time right after changes no row counts — proof the `MERGE` idempotency
actually holds, not just that the job runs without error.

**Verified**, against the real deployed job: executing it twice manually, then a
third time via the actual Cloud Scheduler trigger, left row counts at exactly
14 / 196 / 167 / 167 / 1 across all three runs.

## Real bugs this step caught

- **`window` is a reserved BigQuery keyword.** Caught as a DDL syntax error the
  first time `player_stats` was created — the column is `stat_window`.
- **`matchup_categories.result` and `transactions.player_id` can't be `NOT NULL`.**
  Real `home_stats`/`away_stats` includes attempt-only categories (FGA, FTA, 3PA,
  etc.) with `result: None`, and `recent_activity()`'s action tuples give a player
  *name*, never an id. Both DDL files were corrected (and the live tables recreated,
  while still empty) before writing any data.
- **Staging-table schema autodetection silently picked the wrong type.** A column
  that's all `NULL` in a given run's DataFrame (`transactions.player_id`, always
  `NULL`) has no non-null value for BigQuery to infer a type from. Locally, before
  `pandas-gbq` was added to `ingest/requirements.txt`, autodetect happened to land
  on something MERGE-compatible; once the deployed image included `pandas-gbq`, the
  same load inferred `STRING` against a target column typed `INT64`, and the MERGE
  failed with `Value of type STRING cannot be assigned to T.player_id`. Fixed by
  pinning the staging table's schema to the target table's
  (`client.get_table(...).schema` passed into `LoadJobConfig`) instead of relying on
  autodetection — schema autodetection isn't stable across library versions and
  shouldn't be trusted for a table meant to match a fixed target schema.
- **Cloud Scheduler's HTTP target needs the Cloud Run v2 Jobs API**, not the v1
  `namespaces/.../jobs/{job}:run` path (that path is the older Knative-style route
  meant for Cloud Run *Services*). The correct target:
  `https://{region}-run.googleapis.com/v2/projects/{project}/locations/{region}/jobs/{job}:run`,
  POST, with an empty JSON body (`{}` + `Content-Type: application/json`) and an
  OAuth token from `ingest-sa` (granted `roles/run.invoker` on the job specifically).
  The v1 path returns no error from `gcloud scheduler jobs run` or `jobs describe` —
  it just silently never creates an execution, which only became visible by checking
  `gcloud run jobs executions list` after triggering and seeing nothing new appear.

## Operational pieces now live

- Cloud Scheduler job `espn-ingest-daily`, `0 5 * * *` in `America/Phoenix`,
  triggers `espn-ingest` via the v2 Jobs API using `ingest-sa`'s OAuth token.
- A Cloud Monitoring alerting policy on
  `run.googleapis.com/job/completed_execution_count` (filtered to `result="failed"`
  for this job) emails a notification channel on any failed execution, per the
  "fail loudly" principle above.
