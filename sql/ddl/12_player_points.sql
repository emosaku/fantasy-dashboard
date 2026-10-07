-- Each pool player's fantasy points per stat window in a points league. fp_per_game
-- is ESPN's appliedAverage (bonuses included) when ESPN sent one (source 'espn'),
-- else our stat x points from his per-game line (source 'computed').
-- computed_per_game is always ours, for the daily check against ESPN.
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.player_points` (
  league_id INT64 NOT NULL,
  season INT64 NOT NULL,
  player_id INT64 NOT NULL,
  stat_window STRING NOT NULL,        -- season | last_7 | last_15 | last_30 | projected
  fp_per_game FLOAT64 NOT NULL,
  fp_total FLOAT64,
  games FLOAT64,
  computed_per_game FLOAT64,
  source STRING NOT NULL,             -- espn | computed
  ingested_at TIMESTAMP NOT NULL
)
CLUSTER BY league_id, stat_window;
