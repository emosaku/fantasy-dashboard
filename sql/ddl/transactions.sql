-- Step 3: transactions table -- grain: one row per action (add, drop, or trade leg).
--
-- ESPN's recent_activity() returns one entry per timestamp with a *list* of
-- (team, action, player) tuples -- a trade can bundle several actions under one
-- date. Step 4's ingest transform flattens that list to one row per action here.
-- ESPN gives no stable transaction id, so txn_id is synthesized by ingest as a
-- deterministic hash of (txn_date, team_id, action, player_name) -- that doubles as
-- the natural key, so re-running ingest never duplicates a row.
--
-- player_id comes from ESPN's raw activity message (targetId) since Step 6 read the
-- feed directly; rows loaded before that have it NULL until the next ingest run
-- re-merges them. Nullable all the same, in case a message ever lacks one.
--
-- Natural key for Step 4's MERGE: (txn_id).

CREATE TABLE IF NOT EXISTS `fantasy-dash-emk.fantasy.transactions` (
  txn_id STRING NOT NULL,
  txn_date TIMESTAMP NOT NULL,
  season INT64 NOT NULL,
  team_id INT64 NOT NULL,
  action STRING NOT NULL,  -- FA ADDED, WAIVER ADDED, DROPPED, TRADED, MOVED
  player_id INT64,
  player_name STRING NOT NULL,
  detail STRING,  -- added in Step 6: a lineup move's slots, e.g. 'BE to UT'
  ingested_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(txn_date)
CLUSTER BY team_id;
