-- Step 3: transactions table -- grain: one row per action (add, drop, or trade leg).
--
-- ESPN's recent_activity() returns one entry per timestamp with a *list* of
-- (team, action, player) tuples -- a trade can bundle several actions under one
-- date. Step 4's ingest transform flattens that list to one row per action here.
-- ESPN gives no stable transaction id, so txn_id is synthesized by ingest as a
-- deterministic hash of (txn_date, team_id, action, player_id) -- that doubles as
-- the natural key, so re-running ingest never duplicates a row.
--
-- Natural key for Step 4's MERGE: (txn_id).

CREATE TABLE IF NOT EXISTS `fantasy-dash-emk.fantasy.transactions` (
  txn_id STRING NOT NULL,
  txn_date TIMESTAMP NOT NULL,
  season INT64 NOT NULL,
  team_id INT64 NOT NULL,
  action STRING NOT NULL,  -- ADD, DROP, TRADE
  player_id INT64 NOT NULL,
  player_name STRING NOT NULL,
  ingested_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(txn_date)
CLUSTER BY team_id;
