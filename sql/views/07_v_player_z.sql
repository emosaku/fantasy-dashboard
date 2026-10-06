-- Every pool player's z-score in each of his league's categories, per stat window,
-- plus a 'blended' window (season and projected mixed by games played: alpha =
-- min(season GP / 20, 1)). Means and spreads are over the league's whole pool.
--   count categories: z of the per-game stat
--   ratio categories: z of the volume-weighted impact, num - league_rate x den (for
--     FG% that's (his % - league %) x attempts), so 2-for-2 doesn't beat 9-for-20
-- Lower-is-better categories are sign-flipped: a positive z is always good. `value`
-- is the per-game number (or ratio) shown beside the z; num/den feed team totals.
CREATE OR REPLACE VIEW `{project}.{dataset}.v_player_z` AS
WITH pool AS (
  SELECT DISTINCT
    league_id, season, stat_window, player_id, player_name, position, pro_team,
    team_id, is_free_agent, is_ir, lineup_slot, injury_status
  FROM `{project}.{dataset}.v_player_pool`
),

stats AS (
  SELECT league_id, stat_window, player_id, stat, value
  FROM `{project}.{dataset}.v_player_pool`
),

lines AS (
  SELECT
    p.*,
    c.category,
    c.kind,
    c.lower_is_better,
    c.display_order,
    COALESCE(n.value, 0) AS num,
    COALESCE(d.value, 0) AS den
  FROM pool AS p
  JOIN `{project}.{dataset}.league_categories` AS c
    ON c.league_id = p.league_id
  LEFT JOIN stats AS n
    ON n.league_id = p.league_id AND n.stat_window = p.stat_window
   AND n.player_id = p.player_id AND n.stat = c.num_stat
  LEFT JOIN stats AS d
    ON d.league_id = p.league_id AND d.stat_window = p.stat_window
   AND d.player_id = p.player_id AND d.stat = c.den_stat
),

rates AS (
  SELECT league_id, stat_window, category, SAFE_DIVIDE(SUM(num), SUM(den)) AS rate
  FROM lines
  WHERE kind = 'ratio'
  GROUP BY 1, 2, 3
),

scored AS (
  SELECT
    l.*,
    IF(l.kind = 'ratio', SAFE_DIVIDE(l.num, l.den), l.num) AS value,
    IF(l.lower_is_better, -1, 1)
      * IF(l.kind = 'ratio', IF(l.den > 0, l.num - r.rate * l.den, 0), l.num) AS score
  FROM lines AS l
  LEFT JOIN rates AS r
    USING (league_id, stat_window, category)
),

windowed AS (
  SELECT
    * EXCEPT (score),
    SAFE_DIVIDE(score - AVG(score) OVER c, STDDEV_POP(score) OVER c) AS z
  FROM scored
  WINDOW c AS (PARTITION BY league_id, stat_window, category)
),

season_gp AS (
  SELECT league_id, player_id, value AS gp
  FROM stats
  WHERE stat_window = 'season' AND stat = 'GP'
),

paired AS (
  SELECT
    COALESCE(s.league_id, p.league_id) AS league_id,
    COALESCE(s.season, p.season) AS season,
    COALESCE(s.player_id, p.player_id) AS player_id,
    COALESCE(s.player_name, p.player_name) AS player_name,
    COALESCE(s.position, p.position) AS position,
    COALESCE(s.pro_team, p.pro_team) AS pro_team,
    COALESCE(s.team_id, p.team_id) AS team_id,
    COALESCE(s.is_free_agent, p.is_free_agent) AS is_free_agent,
    COALESCE(s.is_ir, p.is_ir) AS is_ir,
    COALESCE(s.lineup_slot, p.lineup_slot) AS lineup_slot,
    COALESCE(s.injury_status, p.injury_status) AS injury_status,
    COALESCE(s.category, p.category) AS category,
    COALESCE(s.kind, p.kind) AS kind,
    COALESCE(s.lower_is_better, p.lower_is_better) AS lower_is_better,
    COALESCE(s.display_order, p.display_order) AS display_order,
    s.value AS season_value,
    s.z AS season_z,
    p.value AS proj_value,
    p.z AS proj_z,
    IF(p.player_id IS NULL, 1.0, LEAST(COALESCE(g.gp, 0) / 20, 1.0)) AS alpha
  FROM (SELECT * FROM windowed WHERE stat_window = 'season') AS s
  FULL OUTER JOIN (SELECT * FROM windowed WHERE stat_window = 'projected') AS p
    ON p.league_id = s.league_id AND p.player_id = s.player_id AND p.category = s.category
  LEFT JOIN season_gp AS g
    ON g.league_id = COALESCE(s.league_id, p.league_id)
   AND g.player_id = COALESCE(s.player_id, p.player_id)
)

SELECT
  league_id, season, stat_window, player_id, player_name, position, pro_team, team_id,
  is_free_agent, is_ir, lineup_slot, injury_status, category, kind, lower_is_better,
  display_order, num, den, value, z
FROM windowed

UNION ALL

SELECT
  league_id, season, 'blended' AS stat_window, player_id, player_name, position,
  pro_team, team_id, is_free_agent, is_ir, lineup_slot, injury_status, category, kind,
  lower_is_better, display_order,
  CAST(NULL AS FLOAT64) AS num,
  CAST(NULL AS FLOAT64) AS den,
  CASE
    WHEN season_value IS NULL THEN proj_value
    WHEN proj_value IS NULL THEN season_value
    ELSE alpha * season_value + (1 - alpha) * proj_value
  END AS value,
  alpha * COALESCE(season_z, 0) + (1 - alpha) * COALESCE(proj_z, 0) AS z
FROM paired;
