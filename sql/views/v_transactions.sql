-- Step 5: latest transactions with team names joined; counts per team.
-- Feeds the Transactions page.
--
-- Grain: one row per transaction action (same as the raw table). ESPN's
-- raw action labels ('FA ADDED', 'WAIVER ADDED', 'DROPPED', 'TRADED', 'MOVED' -- a
-- lineup move) are kept as `action` for the activity log, and folded into
-- `action_type` (ADD / DROP / TRADE / MOVE)
-- for the page's action filter and per-team bar chart. The per-team counts ride along
-- on every row as window totals, so the page needs no GROUP BY of its own. Any label
-- ESPN adds later falls through as OTHER rather than being dropped.

CREATE OR REPLACE VIEW `fantasy-dash-emk.fantasy.v_transactions` AS
WITH latest_teams AS (
  SELECT season, team_id, team_name
  FROM `fantasy-dash-emk.fantasy.teams`
  QUALIFY ROW_NUMBER() OVER (PARTITION BY season, team_id ORDER BY snapshot_date DESC) = 1
),

typed AS (
  SELECT
    txn_id,
    txn_date,
    season,
    team_id,
    action,
    CASE
      WHEN action IN ('FA ADDED', 'WAIVER ADDED') THEN 'ADD'
      WHEN action = 'DROPPED' THEN 'DROP'
      WHEN action = 'TRADED' THEN 'TRADE'
      WHEN action = 'MOVED' THEN 'MOVE'
      ELSE 'OTHER'
    END AS action_type,
    player_id,
    player_name,
    detail
  FROM `fantasy-dash-emk.fantasy.transactions`
)

SELECT
  x.txn_id,
  x.txn_date,
  x.season,
  x.team_id,
  t.team_name,
  x.action,
  x.action_type,
  x.player_id,
  x.player_name,
  x.detail,
  COUNT(*) OVER team_season AS team_txn_count,
  COUNTIF(x.action_type = 'ADD') OVER team_season AS team_adds,
  COUNTIF(x.action_type = 'DROP') OVER team_season AS team_drops,
  COUNTIF(x.action_type = 'TRADE') OVER team_season AS team_trades,
  COUNTIF(x.action_type = 'MOVE') OVER team_season AS team_moves
FROM typed AS x
LEFT JOIN latest_teams AS t
  ON t.season = x.season
 AND t.team_id = x.team_id
WINDOW team_season AS (PARTITION BY x.season, x.team_id);
