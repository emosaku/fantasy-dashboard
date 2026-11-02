-- LeagueLabWhop: each day's NBA injury list, kept (nba_injuries holds only today's).
-- Shared by every league; written by the nightly NBA update. Re-running a day
-- replaces that day. Grain: day x player (BallDontLie id; nba_players maps to ESPN's).
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.nba_injury_history` (
  snapshot_date DATE NOT NULL,
  player_id INT64 NOT NULL,
  status STRING NOT NULL,
  source_status STRING,
  return_date DATE
)
PARTITION BY snapshot_date
CLUSTER BY player_id;
