-- Step 3: player_stats table -- grain: snapshot_date x player x stat window.
--
-- One row per player per window per day, for every rostered player plus the day's
-- top free agents (added in Step 6, for the waiver analyzer). `stat_window` is one of 'season', 'last_7',
-- 'last_15', 'last_30', or 'projected' (named stat_window, not window -- WINDOW is a
-- reserved keyword in BigQuery SQL, used for window functions). Values are per-game
-- averages, not season totals, so windows of different lengths compare directly.
--
-- 'projected' is included from day one (not just once the season starts): ESPN's
-- real player.stats only populates a 'season'/'last_N' window's total/avg once games
-- have actually been played -- before that they're all zero. 'projected' is already
-- flattened, real data regardless of season state, so Roster Strength and the Trade
-- Analyzer have non-zero numbers to show before Week 1 results exist.
--
-- Natural key for Step 4's MERGE: (season, snapshot_date, player_id, stat_window).

CREATE TABLE IF NOT EXISTS `fantasy-dash-emk.fantasy.player_stats` (
  snapshot_date DATE NOT NULL,
  season INT64 NOT NULL,
  player_id INT64 NOT NULL,
  stat_window STRING NOT NULL,  -- season, last_7, last_15, last_30, projected
  pts FLOAT64,
  reb FLOAT64,
  ast FLOAT64,
  stl FLOAT64,
  blk FLOAT64,
  fg3m FLOAT64,
  fg3a FLOAT64,  -- added in Step 5: 3PT% is a scoring category and needs attempts
  fgm FLOAT64,
  fga FLOAT64,
  ftm FLOAT64,
  fta FLOAT64,
  turnovers FLOAT64,
  gp FLOAT64,  -- added in Step 6: games in the window; blends season stats with projections
  ingested_at TIMESTAMP NOT NULL
)
PARTITION BY snapshot_date
CLUSTER BY player_id, stat_window;
