-- Added in Step 6: each team's strength per category -- the sum of its players'
-- z-scores from v_player_z, leaving out players in an IR slot (they aren't playing).
--
-- Grain: snapshot_date x stat_window x team x category. Feeds v_category_ranks'
-- roster lens. The Trade & Waiver Analyzer computes the same totals in Python
-- (app/analysis) from v_player_z so it can re-total them per simulated move; the
-- two must agree.

CREATE OR REPLACE VIEW `fantasy-dash-emk.fantasy.v_team_category_z` AS
WITH latest_teams AS (
  SELECT season, team_id, team_name
  FROM `fantasy-dash-emk.fantasy.teams`
  QUALIFY ROW_NUMBER() OVER (PARTITION BY season, team_id ORDER BY snapshot_date DESC) = 1
)

SELECT
  z.snapshot_date,
  z.season,
  z.stat_window,
  z.team_id,
  t.team_name,
  z.category,
  SUM(z.z) AS team_z,
  COUNT(*) AS players
FROM `fantasy-dash-emk.fantasy.v_player_z` AS z
LEFT JOIN latest_teams AS t
  ON t.season = z.season
 AND t.team_id = z.team_id
WHERE z.team_id IS NOT NULL
  AND NOT z.is_ir
GROUP BY z.snapshot_date, z.season, z.stat_window, z.team_id, t.team_name, z.category;
