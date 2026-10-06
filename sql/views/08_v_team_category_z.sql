-- Each team's strength per category: its non-IR players' z-scores added up.
-- Grain: league x stat window x team x category.
CREATE OR REPLACE VIEW `{project}.{dataset}.v_team_category_z` AS
SELECT
  z.league_id,
  z.season,
  z.stat_window,
  z.team_id,
  t.team_name,
  z.category,
  ANY_VALUE(z.display_order) AS display_order,
  SUM(z.z) AS team_z,
  COUNT(*) AS players
FROM `{project}.{dataset}.v_player_z` AS z
LEFT JOIN `{project}.{dataset}.teams` AS t
  ON t.league_id = z.league_id AND t.team_id = z.team_id
WHERE z.team_id IS NOT NULL
  AND NOT z.is_ir
GROUP BY z.league_id, z.season, z.stat_window, z.team_id, t.team_name, z.category;
