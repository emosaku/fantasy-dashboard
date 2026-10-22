-- League Lab: ESPN's health details for every pool player (ESPN's written season
-- outlook is ESPN's content and isn't kept).
-- Grain: league x player. Current state.
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.player_details` (
  league_id INT64 NOT NULL,
  season INT64 NOT NULL,
  player_id INT64 NOT NULL,
  injured BOOL,
  injury_status STRING,
  expected_return_date DATE,
  ingested_at TIMESTAMP NOT NULL
)
CLUSTER BY league_id;
