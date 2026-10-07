-- A points league's value for each stat (ESPN scoringSettings.scoringItems[].points),
-- stats worth 0 left out. Categories leagues have no rows.
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.league_scoring` (
  league_id INT64 NOT NULL,
  season INT64 NOT NULL,
  stat STRING NOT NULL,               -- ESPN's abbreviation: PTS, FGA, TO, DD ...
  stat_id INT64 NOT NULL,
  points FLOAT64 NOT NULL,            -- negative for penalties (misses, turnovers)
  display_order INT64 NOT NULL,
  ingested_at TIMESTAMP NOT NULL
)
CLUSTER BY league_id;
