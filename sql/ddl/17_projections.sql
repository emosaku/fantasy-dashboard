-- LeagueLabWhop: our own projected per-game lines (ingest/projections/model.py), the
-- replacement for ESPN's. One set per run (made_at), kept so the backtest and the
-- in-season blend can see what was projected when. Same column names as
-- nba_player_games; gp is projected games. Grain: player x season x run.
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.projections` (
  player_id INT64 NOT NULL,           -- BallDontLie's id
  season INT64 NOT NULL,
  made_at TIMESTAMP NOT NULL,
  model_version STRING NOT NULL,
  kind STRING NOT NULL,               -- preseason | blended
  gp FLOAT64,
  min FLOAT64, pts FLOAT64, reb FLOAT64, oreb FLOAT64, dreb FLOAT64, ast FLOAT64,
  stl FLOAT64, blk FLOAT64, tov FLOAT64, fgm FLOAT64, fga FLOAT64, fg3m FLOAT64,
  fg3a FLOAT64, ftm FLOAT64, fta FLOAT64,
  age FLOAT64,
  history_minutes FLOAT64
)
CLUSTER BY season, player_id;
