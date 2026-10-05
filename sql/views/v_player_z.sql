-- Added in Step 6: every pool player's z-score in each of the 9 categories -- the
-- shared foundation Category Rankings and the Trade & Waiver Analyzer both read.
--
-- Grain: snapshot_date x stat_window x player x category. Means and spreads are taken
-- over the whole v_player_pool (rostered players + top free agents) for that snapshot
-- and window.
--
-- Counting categories (pts, reb, ast, stl, blk, fg3m): z = (x - mean) / sd of the
-- per-game average. A missing stat counts as 0.
--
-- Percentages (fg_pct, ft_pct, fg3_pct) are weighted by volume, so a 50% shooter on
-- 2 attempts doesn't outrank a 48% shooter on 20:
--   impact = (player % - league %) x attempts, where league % = pooled makes / pooled
--   attempts; z is then taken over impact. 0 attempts means impact 0.
-- This league scores 3PT%, not turnovers, so 3PT% gets the same treatment as FG% and
-- FT% (3PM over 3PA), and no category needs a sign flip.
--
-- 'blended' is an extra stat_window: each player's season and projected z mixed by
-- games played, alpha = min(season GP / 20, 1) -- all projection before his first
-- game, all season stats from game 20 on. A player with only one of the two uses it
-- alone. `value` is the raw per-game number (or percentage) shown next to the z,
-- blended the same way.

CREATE OR REPLACE VIEW `fantasy-dash-emk.fantasy.v_player_z` AS
WITH base AS (
  SELECT
    *,
    SAFE_DIVIDE(SUM(fgm) OVER w, SUM(fga) OVER w) AS league_fg_pct,
    SAFE_DIVIDE(SUM(ftm) OVER w, SUM(fta) OVER w) AS league_ft_pct,
    SAFE_DIVIDE(SUM(fg3m) OVER w, SUM(fg3a) OVER w) AS league_fg3_pct
  FROM `fantasy-dash-emk.fantasy.v_player_pool`
  WINDOW w AS (PARTITION BY snapshot_date, stat_window)
),

-- One row per player x category: `value` is what's displayed, `score` is what's
-- standardized (the value itself, or the volume-weighted impact for percentages).
scored AS (
  SELECT
    snapshot_date, season, stat_window, player_id, player_name, position, pro_team,
    team_id, is_free_agent, is_ir, lineup_slot, injury_status, gp,
    category, value, score
  FROM base,
  UNNEST([
    STRUCT('pts' AS category, COALESCE(pts, 0) AS value, COALESCE(pts, 0) AS score),
    ('reb', COALESCE(reb, 0), COALESCE(reb, 0)),
    ('ast', COALESCE(ast, 0), COALESCE(ast, 0)),
    ('stl', COALESCE(stl, 0), COALESCE(stl, 0)),
    ('blk', COALESCE(blk, 0), COALESCE(blk, 0)),
    ('fg3m', COALESCE(fg3m, 0), COALESCE(fg3m, 0)),
    ('fg_pct', SAFE_DIVIDE(fgm, fga),
      IF(COALESCE(fga, 0) > 0, (fgm / fga - league_fg_pct) * fga, 0)),
    ('ft_pct', SAFE_DIVIDE(ftm, fta),
      IF(COALESCE(fta, 0) > 0, (ftm / fta - league_ft_pct) * fta, 0)),
    ('fg3_pct', SAFE_DIVIDE(fg3m, fg3a),
      IF(COALESCE(fg3a, 0) > 0, (COALESCE(fg3m, 0) / fg3a - league_fg3_pct) * fg3a, 0))
  ])
),

windowed AS (
  SELECT
    * EXCEPT (score),
    SAFE_DIVIDE(
      score - AVG(score) OVER c,
      STDDEV_POP(score) OVER c
    ) AS z
  FROM scored
  WINDOW c AS (PARTITION BY snapshot_date, stat_window, category)
),

-- Season and projected side by side for the blend.
paired AS (
  SELECT
    COALESCE(s.snapshot_date, p.snapshot_date) AS snapshot_date,
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
    s.gp,
    COALESCE(s.category, p.category) AS category,
    s.value AS season_value,
    s.z AS season_z,
    p.value AS proj_value,
    p.z AS proj_z,
    -- No projection: season stats carry the full weight regardless of games played.
    IF(p.player_id IS NULL, 1.0, LEAST(COALESCE(s.gp, 0) / 20, 1.0)) AS alpha
  FROM (SELECT * FROM windowed WHERE stat_window = 'season') AS s
  FULL OUTER JOIN (SELECT * FROM windowed WHERE stat_window = 'projected') AS p
    ON p.snapshot_date = s.snapshot_date
   AND p.player_id = s.player_id
   AND p.category = s.category
)

SELECT
  snapshot_date, season, stat_window, player_id, player_name, position, pro_team,
  team_id, is_free_agent, is_ir, lineup_slot, injury_status, gp, category, value, z
FROM windowed

UNION ALL

SELECT
  snapshot_date, season, 'blended' AS stat_window, player_id, player_name, position,
  pro_team, team_id, is_free_agent, is_ir, lineup_slot, injury_status, gp, category,
  CASE
    WHEN season_value IS NULL THEN proj_value
    WHEN proj_value IS NULL THEN season_value
    ELSE alpha * season_value + (1 - alpha) * proj_value
  END AS value,
  alpha * COALESCE(season_z, 0) + (1 - alpha) * COALESCE(proj_z, 0) AS z
FROM paired;
