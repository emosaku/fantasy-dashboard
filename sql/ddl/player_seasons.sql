-- Added in Step 6: player_seasons table -- grain: player x past season.
--
-- Games played in each of the last 3 completed seasons, for every player in the pool
-- (rostered + top free agents), read from ESPN's league endpoint for that past season.
-- v_player_profile averages it into "average games played" -- how durable a player
-- has been -- shown in the Trade Analyzer's mock trade. A season with no ESPN line
-- for the player (not in the NBA yet) has no row rather than a 0.
--
-- `season` is the current season the row was loaded in; `history_season` is the past
-- season it describes (ESPN's convention: 2026 = the 2025-26 season).
--
-- Natural key for Step 4's MERGE: (season, player_id, history_season).

CREATE TABLE IF NOT EXISTS `fantasy-dash-emk.fantasy.player_seasons` (
  season INT64 NOT NULL,
  player_id INT64 NOT NULL,
  history_season INT64 NOT NULL,
  games_played FLOAT64 NOT NULL,
  ingested_at TIMESTAMP NOT NULL
)
CLUSTER BY player_id;
