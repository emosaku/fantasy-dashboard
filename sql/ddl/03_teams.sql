-- League Lab: teams and their real records. Grain: league x team. Current state.
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.teams` (
  league_id INT64 NOT NULL,
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
CLUSTER BY league_id, team_id;
