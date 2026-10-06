-- League Lab: per-game averages for every pool player (rostered + free agents), in
-- long format so any league's categories can be built from them: one row per player
-- x stat window x stat (PTS, REB, FGM, FGA, TO, GP ...). stat_window is season,
-- last_7, last_15, last_30 or projected. Grain: league x player x window x stat.
-- Current state.
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.player_stats` (
  league_id INT64 NOT NULL,
  season INT64 NOT NULL,
  player_id INT64 NOT NULL,
  stat_window STRING NOT NULL,
  stat STRING NOT NULL,
  value FLOAT64,
  ingested_at TIMESTAMP NOT NULL
)
CLUSTER BY league_id, stat_window;
