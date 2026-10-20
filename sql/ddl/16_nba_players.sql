-- LeagueLabWhop: NBA players from BallDontLie, plus what it doesn't have: each
-- player's birth date (the projection model's aging) and ESPN player id (to join
-- League Lab's ESPN-keyed tables: rosters, free agents), both matched from Wikidata
-- by scripts/match_players.py. NULL until matched. Grain: player. Current state.
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.nba_players` (
  player_id INT64 NOT NULL,           -- BallDontLie's id
  player_name STRING,
  team STRING,
  position STRING,
  draft_year INT64,                   -- the age estimate when a birth date is missing
  birth_date DATE,
  espn_player_id INT64,
  ingested_at TIMESTAMP NOT NULL
)
CLUSTER BY player_id;
