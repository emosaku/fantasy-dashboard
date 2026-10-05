-- Step 5: sums each roster's per-game player stats (last 15 days); z-scores each
-- category across the league. Feeds the Roster Strength page.
--
-- Grain: team x stat_window. Built on v_team_roster_stats so the roster-to-stats join
-- lives in one place. Every window is kept (not just last_15) because the page has a
-- 7/15/30-day selector, and before the season only 'projected' has data. Players in
-- the IR slot are left out -- they aren't playing, so they don't add strength.
--
-- Counting stats are summed per-game averages; percentages are recomputed from the
-- summed makes and attempts. Each *_z column is how many standard deviations the team
-- sits above (+) or below (-) the league average for that window -- the heatmap's
-- values. Higher is better in all 9 categories, so no sign flips are needed.

CREATE OR REPLACE VIEW `fantasy-dash-emk.fantasy.v_roster_strength` AS
WITH totals AS (
  SELECT
    season,
    team_id,
    ANY_VALUE(team_name) AS team_name,
    stat_window,
    COUNT(*) AS players,
    SAFE_DIVIDE(SUM(fgm), SUM(fga)) AS fg_pct,
    SAFE_DIVIDE(SUM(ftm), SUM(fta)) AS ft_pct,
    SUM(fg3m) AS fg3m,
    SAFE_DIVIDE(SUM(fg3m), SUM(fg3a)) AS fg3_pct,
    SUM(reb) AS reb,
    SUM(ast) AS ast,
    SUM(stl) AS stl,
    SUM(blk) AS blk,
    SUM(pts) AS pts
  FROM `fantasy-dash-emk.fantasy.v_team_roster_stats`
  WHERE lineup_slot IS DISTINCT FROM 'IR'
  GROUP BY season, team_id, stat_window
)

SELECT
  *,
  SAFE_DIVIDE(fg_pct - AVG(fg_pct) OVER w, STDDEV_POP(fg_pct) OVER w) AS fg_pct_z,
  SAFE_DIVIDE(ft_pct - AVG(ft_pct) OVER w, STDDEV_POP(ft_pct) OVER w) AS ft_pct_z,
  SAFE_DIVIDE(fg3m - AVG(fg3m) OVER w, STDDEV_POP(fg3m) OVER w) AS fg3m_z,
  SAFE_DIVIDE(fg3_pct - AVG(fg3_pct) OVER w, STDDEV_POP(fg3_pct) OVER w) AS fg3_pct_z,
  SAFE_DIVIDE(reb - AVG(reb) OVER w, STDDEV_POP(reb) OVER w) AS reb_z,
  SAFE_DIVIDE(ast - AVG(ast) OVER w, STDDEV_POP(ast) OVER w) AS ast_z,
  SAFE_DIVIDE(stl - AVG(stl) OVER w, STDDEV_POP(stl) OVER w) AS stl_z,
  SAFE_DIVIDE(blk - AVG(blk) OVER w, STDDEV_POP(blk) OVER w) AS blk_z,
  SAFE_DIVIDE(pts - AVG(pts) OVER w, STDDEV_POP(pts) OVER w) AS pts_z
FROM totals
WINDOW w AS (PARTITION BY season, stat_window);
