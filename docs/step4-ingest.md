# Step 4: Ingest job

Step 3 built the empty BigQuery tables. Step 4 is what fills them — a
containerized Python job that pulls the league from ESPN and loads it into
BigQuery on a schedule. This is the one piece of the whole project that actually
talks to ESPN; everything downstream (views, dashboard) only ever reads BigQuery.

The job started with five tables. Step 6's features added four more (`free_agents`,
`league_status`, `player_seasons`, `player_details`), a few columns, and a direct
read of ESPN's activity feed; this doc describes the job as it runs now, and
[What Step 6 added](#what-step-6-added) lists those changes.

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

At the start of Step 4, `ingest/main.py` was still a `raise NotImplementedError` stub.

## The job, end to end

```
Cloud Scheduler (5:00 AM AZ, daily)
        │ triggers
        ▼
Cloud Run Job: espn-ingest
        │ 1. reads ESPN_S2/SWID from Secret Manager (injected as env vars)
        │ 2. builds espn_api.basketball.League; reads ESPN's raw activity and
        │    player-info feeds where espn_api drops fields
        │ 3. transforms each source to a DataFrame
        │ 4. loads each into a staging table, then MERGEs into the real table
        ▼
BigQuery: fantasy.{teams, matchup_categories, rosters, player_stats, transactions,
                   free_agents, league_status, player_seasons, player_details}

Also triggered on demand by the dashboard's Refresh data button (Step 6).
```

## Transform logic per table

This is the real engineering work in this step — turning each `espn-api` object's
actual (not documented) shape into the flat rows each table expects.

### `teams`
Straightforward — one row per team per ingest run. `league.teams` already gives
`team_id`, `team_name`, `wins`, `losses`, `standing` directly as flat attributes.
`owner` is the manager's real first and last name (what ESPN's site shows), falling
back to the ESPN username only when the account has no name.

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
`position` (`.position`), `lineup_slot`, `injury_status` and ESPN's
`expected_return_date` (usually empty) directly.

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
3. Skips a window ESPN hasn't filled in yet (no `avg` block), which before the
   season means everything but `'projected'`

It covers every rostered player **and** the day's top 100 free agents, and stores
`fg3a` (3PT% is a scoring category) and `gp` (games played in the window, used to
blend season stats with projections) alongside the categories.

### `transactions`
Every activity this season — free-agent and waiver adds, drops, trades, and lineup
moves — read straight from ESPN's league communication feed (`fetch_activity`), not
through `league.recent_activity()`. espn_api throws away two things the raw messages
carry: the team on a lineup move and the player id on every action. Each activity
topic can bundle several messages (a trade's legs), so the transform writes one row
per message. The feed is read page by page (50 at a time, by offset) until a short
page comes back, so a busy day can never push activity out of reach.

Since ESPN provides no stable transaction id, `txn_id` is a deterministic hash of
`(date, team_id, action, player_name)` — the same recipe from day one, so rows loaded
before the switch still match — which is what makes the `MERGE` idempotent here.
Lineup moves also store `detail`, the slots moved between (`BE to UT`).

### `free_agents`, `league_status`, `player_details`, `player_seasons`
- `free_agents`: `league.free_agents(size=100)` — the waiver pool the Trade Analyzer
  recommends from and part of the z-score player pool.
- `league_status`: one row per run — current matchup period and the number of
  regular-season periods (16), which the season projection needs.
- `player_details`: for every pool player, ESPN's injured flag, injury status, return
  date and written season outlook, from the `kona_player_info` view.
- `player_seasons`: games played in each of the last 3 completed seasons, from the
  same view requested against each past season's league endpoint
  (`fetch_player_info`). A season with no NBA line for the player gets no row.

## Idempotency: staging table + MERGE

Every table follows the same pattern, so re-running the job (intentionally, or
because Cloud Scheduler fires twice) never duplicates rows:

1. Load the day's transformed DataFrame into a `_staging` table (overwrite each run)
2. `MERGE` the target table against staging, matching on that table's natural key
   (documented in each `sql/ddl/*.sql` file's header comment)
3. On match: update the row (handles corrections, e.g. a late stat update). On no
   match: insert.
4. Tables keyed by `snapshot_date` (`teams`, `rosters`, `player_stats`, `free_agents`,
   `league_status`, `player_details`) hold one complete picture per day, so the
   `MERGE` also deletes that day's rows the run no longer has
   (`WHEN NOT MATCHED BY SOURCE AND T.snapshot_date = <today> THEN DELETE`). Without
   it, a player dropped between two same-day runs kept his old roster row until the
   next day. An empty pull never deletes anything.

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

A manual `gcloud run jobs execute espn-ingest` fills every table, and running it
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

## What Step 6 added

The dashboard's later features needed more from ESPN. Each change was deployed with
the same `gcloud run jobs deploy` command, run at least twice, and checked for
identical row counts.

| Change | Why |
|---|---|
| `player_stats.fg3a`, `player_stats.gp` | 3PT% is a scoring category (needs attempts); games played blends season stats with projections |
| Top 100 free agents: `free_agents` table + their `player_stats` rows | The waiver analyzer and the z-score player pool |
| `league_status` table | The season projection needs the current week and season length |
| `rosters.expected_return_date` | The injury-aware projection uses ESPN's return date when there is one |
| `teams.owner` = real name | ESPN's username (`ESPNFAN6474865950`) isn't who the league knows |
| `transactions` from the raw activity feed: every page, lineup moves, `player_id`, `detail` | The activity log shows every activity; espn_api drops a move's team and every player id |
| `player_details`, `player_seasons` tables | Health details and 3 seasons of games played for the Trade Analyzer's mock trade |
| Snapshot tables replace the day's rows (`MERGE ... WHEN NOT MATCHED BY SOURCE`) | A player dropped mid-day lingered on his old roster |

Counts after the latest pair of runs: `teams` 14, `matchup_categories` 196,
`rosters` 169, `player_stats` 254, `transactions` 27 (5 adds/drops + 22 lineup
moves), `free_agents` 100, `league_status` 1, `player_details` 269, `player_seasons`
686 (208 / 231 / 247 players across the three seasons).

More real bugs these changes caught:

- **A mid-day drop left a stale roster row.** `MERGE` only inserted and updated, so
  Malik Monk stayed on team 14 for the rest of the day after being dropped. Fixed by
  the snapshot delete above, with a test on the generated SQL.
- **espn_api's lineup moves have a string where a team should be.** Asking
  `recent_activity()` for moves made the job crash (`'str' object has no attribute
  'team_id'`): the library leaves the team blank on a move. The raw message has it
  (`for`), so the feed is now read directly.
- **ESPN rejects a `limit` without a sort.** The player-info request returned
  `400: Limit request must be accompanied by a sort`; the id filter already bounds
  the result, so the limit was dropped (checked: 100 of 100 players come back).
