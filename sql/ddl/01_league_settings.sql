-- League Lab: one row per league -- how it's set up on ESPN, refreshed every ingest run.
-- Grain: league. Current state (replaced per league each run), not history.
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.league_settings` (
  league_id INT64 NOT NULL,
  season INT64 NOT NULL,
  league_name STRING,
  scoring_type STRING NOT NULL,       -- H2H_MOST_CATEGORIES or H2H_EACH_CATEGORY
  team_count INT64 NOT NULL,
  current_matchup_period INT64 NOT NULL,
  reg_season_matchup_periods INT64 NOT NULL,
  playoff_team_count INT64,
  ingested_at TIMESTAMP NOT NULL
)
CLUSTER BY league_id;
