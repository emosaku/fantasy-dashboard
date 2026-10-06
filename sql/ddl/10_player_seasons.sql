-- League Lab: games played per past NBA season -- the same for every league, so it's
-- shared, not per league. Ingest only fetches players it hasn't seen. games_played is
-- NULL when the player had no NBA line that season (recorded so he isn't re-fetched).
-- Grain: player x past season.
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.player_seasons` (
  player_id INT64 NOT NULL,
  history_season INT64 NOT NULL,
  games_played FLOAT64,
  ingested_at TIMESTAMP NOT NULL
)
CLUSTER BY player_id;
