-- Added in Step 6: free_agents table -- grain: snapshot_date x player.
--
-- The day's top free agents from league.free_agents(size=100), in ESPN's own order.
-- They're the waiver pool the Trade & Waiver Analyzer recommends pickups from, and
-- they join rostered players in the z-score player pool (v_player_pool), so league
-- means and spreads reflect who's realistically available, not just who's rostered.
-- Their per-game stat lines land in player_stats alongside rostered players'.
--
-- Natural key for Step 4's MERGE: (season, snapshot_date, player_id).

CREATE TABLE IF NOT EXISTS `fantasy-dash-emk.fantasy.free_agents` (
  snapshot_date DATE NOT NULL,
  season INT64 NOT NULL,
  player_id INT64 NOT NULL,
  player_name STRING NOT NULL,
  position STRING,
  pro_team STRING,
  injury_status STRING,  -- ACTIVE, DAY_TO_DAY, OUT, ...
  ingested_at TIMESTAMP NOT NULL
)
PARTITION BY snapshot_date
CLUSTER BY player_id;
