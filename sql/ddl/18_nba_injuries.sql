-- LeagueLabWhop: current NBA injury status from BallDontLie ALL-STAR, replacing ESPN's
-- (docs/whopDocs/nightly-update.md). Status and expected return only; the written
-- injury notes aren't kept. status uses the codes the pages already read (OUT,
-- DAY_TO_DAY, ACTIVE); source_status is BallDontLie's own word (Questionable ...).
-- A player missing from the table is healthy. Grain: player. Current state, replaced
-- each night.
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.nba_injuries` (
  player_id INT64 NOT NULL,           -- BallDontLie's id
  status STRING NOT NULL,
  source_status STRING,
  return_date DATE,
  ingested_at TIMESTAMP NOT NULL
);
