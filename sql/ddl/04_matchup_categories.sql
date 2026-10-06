-- League Lab: every matchup's category totals from ESPN box scores, one row per side.
-- Grain: league x matchup period x team x stat. Accumulates over the season; ingest
-- replaces only the periods it re-fetches (still-open ones), never finished weeks.
-- `category` holds every stat ESPN reports, including makes/attempts (FGM, FGA...)
-- that ratio categories are recomputed from; `result` is ESPN's W/L/T for scored
-- categories, NULL for attempt-only stats.
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.matchup_categories` (
  league_id INT64 NOT NULL,
  season INT64 NOT NULL,
  matchup_period INT64 NOT NULL,
  team_id INT64 NOT NULL,
  opponent_id INT64 NOT NULL,
  category STRING NOT NULL,
  value FLOAT64 NOT NULL,
  result STRING,
  ingested_at TIMESTAMP NOT NULL
)
CLUSTER BY league_id, matchup_period, team_id;
