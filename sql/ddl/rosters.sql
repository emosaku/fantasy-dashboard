-- Step 3: rosters table -- grain: snapshot_date x team x player.
--
-- One row per player per team per day the ingest job runs -- a daily roster snapshot,
-- so trades/adds/drops show up as the player moving to a new team_id on a later
-- snapshot_date rather than overwriting history. Feeds v_team_roster_stats (Step 5)
-- for Roster Strength and Mock Trade Analysis.
--
-- Natural key for Step 4's MERGE: (season, snapshot_date, team_id, player_id).

CREATE TABLE IF NOT EXISTS `fantasy-dash-emk.fantasy.rosters` (
  snapshot_date DATE NOT NULL,
  season INT64 NOT NULL,
  team_id INT64 NOT NULL,
  player_id INT64 NOT NULL,
  player_name STRING NOT NULL,
  position STRING,
  lineup_slot STRING,
  injury_status STRING,
  expected_return_date DATE,  -- added in Step 6: ESPN's estimate, often NULL; feeds the
                              -- injury-aware season projection
  ingested_at TIMESTAMP NOT NULL
)
PARTITION BY snapshot_date
CLUSTER BY team_id, player_id;
