-- League Lab: ESPN's health details and season outlook for every pool player.
-- Grain: league x player. Current state.
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.player_details` (
  league_id INT64 NOT NULL,
  season INT64 NOT NULL,
  player_id INT64 NOT NULL,
  injured BOOL,
  injury_status STRING,
  expected_return_date DATE,
  season_outlook STRING,
  ingested_at TIMESTAMP NOT NULL
)
CLUSTER BY league_id;
