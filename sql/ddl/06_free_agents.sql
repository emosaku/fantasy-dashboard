-- League Lab: the league's top free agents (ESPN's order). Grain: league x player.
-- Current state.
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.free_agents` (
  league_id INT64 NOT NULL,
  season INT64 NOT NULL,
  player_id INT64 NOT NULL,
  player_name STRING NOT NULL,
  position STRING,
  pro_team STRING,
  injury_status STRING,
  eligible_slots STRING,
  ingested_at TIMESTAMP NOT NULL
)
CLUSTER BY league_id;

-- Added for points leagues (CREATE IF NOT EXISTS doesn't add columns to an
-- existing table).
ALTER TABLE `{project}.{dataset}.free_agents`
  ADD COLUMN IF NOT EXISTS eligible_slots STRING;
