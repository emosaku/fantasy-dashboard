-- League Lab: who's on each roster. Grain: league x team x player. Current state.
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.rosters` (
  league_id INT64 NOT NULL,
  season INT64 NOT NULL,
  team_id INT64 NOT NULL,
  player_id INT64 NOT NULL,
  player_name STRING NOT NULL,
  position STRING,
  lineup_slot STRING,
  injury_status STRING,
  expected_return_date DATE,
  pro_team STRING,
  eligible_slots STRING,             -- lineup slots he can start in: PG,G,UT ...
  ingested_at TIMESTAMP NOT NULL
)
CLUSTER BY league_id, team_id;

-- Added for points leagues (CREATE IF NOT EXISTS doesn't add columns to an
-- existing table).
ALTER TABLE `{project}.{dataset}.rosters`
  ADD COLUMN IF NOT EXISTS pro_team STRING,
  ADD COLUMN IF NOT EXISTS eligible_slots STRING;
