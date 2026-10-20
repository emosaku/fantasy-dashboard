-- LeagueLabWhop: NBA players from BallDontLie, with the birth date the projection
-- model's aging needs and the matching ESPN player id, so projections join League
-- Lab's ESPN-keyed tables (rosters, free agents). espn_player_id is NULL until the
-- player is matched. Grain: player. Current state.
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.nba_players` (
  player_id INT64 NOT NULL,           -- BallDontLie's id
  player_name STRING,
  team STRING,
  position STRING,
  birth_date DATE,
  espn_player_id INT64,
  ingested_at TIMESTAMP NOT NULL
)
CLUSTER BY player_id;
