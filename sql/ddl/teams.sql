-- Step 3: teams table -- grain: team x snapshot_date.
--
-- One row per team per day the ingest job runs, so standings/records are a queryable
-- history rather than only "whatever ESPN shows right now". Natural key for Step 4's
-- staging-table MERGE: (season, snapshot_date, team_id).

CREATE TABLE IF NOT EXISTS `fantasy-dash-emk.fantasy.teams` (
  snapshot_date DATE NOT NULL,
  season INT64 NOT NULL,
  team_id INT64 NOT NULL,
  team_name STRING NOT NULL,
  owner STRING,
  wins INT64 NOT NULL,
  losses INT64 NOT NULL,
  ties INT64 NOT NULL,
  standing INT64,
  ingested_at TIMESTAMP NOT NULL
)
PARTITION BY snapshot_date
CLUSTER BY team_id;
