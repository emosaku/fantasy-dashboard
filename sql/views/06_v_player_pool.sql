-- Every rostered player and top free agent in each league, with each per-game stat
-- (long: one row per player x stat window x stat). team_id NULL = free agent.
CREATE OR REPLACE VIEW `{project}.{dataset}.v_player_pool` AS
WITH pool AS (
  SELECT
    league_id, season, player_id, player_name, position,
    CAST(NULL AS STRING) AS pro_team, team_id, lineup_slot, injury_status,
    expected_return_date
  FROM `{project}.{dataset}.rosters`

  UNION ALL

  SELECT
    league_id, season, player_id, player_name, position,
    pro_team, CAST(NULL AS INT64) AS team_id, CAST(NULL AS STRING) AS lineup_slot,
    injury_status, CAST(NULL AS DATE) AS expected_return_date
  FROM `{project}.{dataset}.free_agents`
)

SELECT
  p.*,
  p.team_id IS NULL AS is_free_agent,
  COALESCE(p.lineup_slot = 'IR', FALSE) AS is_ir,
  s.stat_window,
  s.stat,
  s.value
FROM pool AS p
JOIN `{project}.{dataset}.player_stats` AS s
  ON s.league_id = p.league_id AND s.player_id = p.player_id;
