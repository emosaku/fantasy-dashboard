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
  ingested_at TIMESTAMP NOT NULL
)
CLUSTER BY league_id, team_id;
