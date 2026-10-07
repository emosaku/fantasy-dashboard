-- Every matchup of a points league's season, played or not, one row per side: the
-- week's points (live for the current week; 0 before it's played) and the opponent.
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.matchup_scores` (
  league_id INT64 NOT NULL,
  season INT64 NOT NULL,
  matchup_period INT64 NOT NULL,
  team_id INT64 NOT NULL,
  opponent_id INT64 NOT NULL,
  points FLOAT64 NOT NULL,
  opponent_points FLOAT64 NOT NULL,
  is_playoff BOOL NOT NULL,
  winner STRING,                      -- HOME | AWAY | TIE | UNDECIDED
  is_home BOOL NOT NULL,
  ingested_at TIMESTAMP NOT NULL
)
CLUSTER BY league_id, matchup_period;
