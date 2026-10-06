-- Every activity with team names, ESPN's raw label (`action`) folded into
-- `action_type` (ADD / DROP / TRADE / MOVE / OTHER), and per-team counts.
CREATE OR REPLACE VIEW `{project}.{dataset}.v_transactions` AS
WITH typed AS (
  SELECT
    *,
    CASE
      WHEN action IN ('FA ADDED', 'WAIVER ADDED') THEN 'ADD'
      WHEN action = 'DROPPED' THEN 'DROP'
      WHEN action = 'TRADED' THEN 'TRADE'
      WHEN action = 'MOVED' THEN 'MOVE'
      ELSE 'OTHER'
    END AS action_type
  FROM `{project}.{dataset}.transactions`
)

SELECT
  x.league_id,
  x.season,
  x.txn_id,
  x.txn_date,
  x.team_id,
  t.team_name,
  x.action,
  x.action_type,
  x.player_id,
  x.player_name,
  x.detail,
  COUNT(*) OVER team AS team_txn_count,
  COUNTIF(x.action_type = 'ADD') OVER team AS team_adds,
  COUNTIF(x.action_type = 'DROP') OVER team AS team_drops,
  COUNTIF(x.action_type = 'TRADE') OVER team AS team_trades,
  COUNTIF(x.action_type = 'MOVE') OVER team AS team_moves
FROM typed AS x
LEFT JOIN `{project}.{dataset}.teams` AS t
  ON t.league_id = x.league_id AND t.team_id = x.team_id
WINDOW team AS (PARTITION BY x.league_id, x.season, x.team_id);
