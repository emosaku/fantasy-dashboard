-- The Draft Tool's player pool: the 400 best players by ESPN's draft rank for the
-- league's format (STANDARD for points, ROTO for categories), rostered or not, with
-- what the draft model reads. Reloaded every run.
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.draft_pool` (
  league_id INT64 NOT NULL,
  season INT64 NOT NULL,
  player_id INT64 NOT NULL,
  player_name STRING NOT NULL,
  pro_team STRING,
  position STRING,                    -- primary position: PG, SG, SF, PF, C
  eligible_slots STRING,              -- lineup slots he can start in: PG,G,UT ...
  injury_status STRING,
  adp FLOAT64,                        -- ESPN's average draft position (all leagues)
  auction_value FLOAT64,
  percent_owned FLOAT64,
  rank INT64,                         -- ESPN's STANDARD (points) draft rank
  rank_roto INT64,                    -- ESPN's ROTO (categories) draft rank
  proj_fpg FLOAT64,                   -- points leagues: ESPN's applied average, else ours
  proj_games FLOAT64,                 -- ESPN's projected games
  last_season_games FLOAT64,
  history_games FLOAT64,              -- average games over his last 3 seasons
  ingested_at TIMESTAMP NOT NULL
)
CLUSTER BY league_id;
