-- Each draft-pool player's projected per-game line (long: player x stat), for a
-- categories draft's z-scores.
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.draft_pool_stats` (
  league_id INT64 NOT NULL,
  season INT64 NOT NULL,
  player_id INT64 NOT NULL,
  stat STRING NOT NULL,
  value FLOAT64 NOT NULL,
  ingested_at TIMESTAMP NOT NULL
)
CLUSTER BY league_id;
