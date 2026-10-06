-- League Lab: every add, drop, trade and lineup move. Grain: league x action.
-- Accumulates; ingest only fetches activity newer than what it already has.
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.transactions` (
  league_id INT64 NOT NULL,
  season INT64 NOT NULL,
  txn_id STRING NOT NULL,
  txn_date TIMESTAMP NOT NULL,
  team_id INT64,
  action STRING NOT NULL,
  player_id INT64,
  player_name STRING NOT NULL,
  detail STRING,
  ingested_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(txn_date)
CLUSTER BY league_id;
