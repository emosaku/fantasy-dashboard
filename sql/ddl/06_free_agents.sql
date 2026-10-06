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
  ingested_at TIMESTAMP NOT NULL
)
CLUSTER BY league_id;
