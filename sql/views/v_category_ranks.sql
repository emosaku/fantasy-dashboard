-- Added in Step 6: every team ranked 1-14 in every category, through two lenses.
-- Feeds the Category Rankings tab of the Roster Strength page.
--
-- Grain: snapshot_date x stat_window x lens x team x category.
--
--   lens = 'roster'  -- forward-looking: team z totals (v_team_category_z) for each
--                       stat window. Works before games start.
--   lens = 'results' -- what actually happened in finished weeks (matchup periods
--                       before league_status.current_matchup_period): counting
--                       categories are the average weekly value; percentages are
--                       pooled makes / attempts over those weeks (the box scores do
--                       store makes and attempts, so no averaging of percentages).
--                       win_rate = share of the other teams the team beat in that
--                       category, ties half, averaged over weeks. stat_window is
--                       NULL. Empty until week 1 finishes.
--
-- Rank 1 is best; higher is better in all 9 categories. Ties share a rank (RANK()).
-- gap_above / gap_below = distance to the next-better / next-worse team's value
-- (team-z units in the roster lens), NULL at the top / bottom.

CREATE OR REPLACE VIEW `fantasy-dash-emk.fantasy.v_category_ranks` AS
WITH status AS (
  SELECT snapshot_date, season, current_matchup_period
  FROM `fantasy-dash-emk.fantasy.league_status`
  QUALIFY ROW_NUMBER() OVER (ORDER BY season DESC, snapshot_date DESC) = 1
),

latest_teams AS (
  SELECT t.team_id, t.team_name
  FROM `fantasy-dash-emk.fantasy.teams` AS t
  JOIN status AS s
    ON s.season = t.season
  QUALIFY ROW_NUMBER() OVER (PARTITION BY t.team_id ORDER BY t.snapshot_date DESC) = 1
),

roster AS (
  SELECT
    snapshot_date,
    stat_window,
    'roster' AS lens,
    team_id,
    team_name,
    category,
    team_z AS value,
    CAST(NULL AS FLOAT64) AS win_rate
  FROM `fantasy-dash-emk.fantasy.v_team_category_z`
),

finished_weeks AS (
  SELECT w.*
  FROM `fantasy-dash-emk.fantasy.v_team_week_cats` AS w
  JOIN status AS s
    ON s.season = w.season
  WHERE w.matchup_period < s.current_matchup_period
),

season_lines AS (
  SELECT
    team_id,
    SAFE_DIVIDE(SUM(fgm), SUM(fga)) AS fg_pct,
    SAFE_DIVIDE(SUM(ftm), SUM(fta)) AS ft_pct,
    AVG(fg3m) AS fg3m,
    SAFE_DIVIDE(SUM(fg3m), SUM(fg3a)) AS fg3_pct,
    AVG(reb) AS reb,
    AVG(ast) AS ast,
    AVG(stl) AS stl,
    AVG(blk) AS blk,
    AVG(pts) AS pts
  FROM finished_weeks
  GROUP BY team_id
),

season_values AS (
  SELECT team_id, category, value
  FROM season_lines
  UNPIVOT INCLUDE NULLS (
    value FOR category IN (fg_pct, ft_pct, fg3m, fg3_pct, reb, ast, stl, blk, pts)
  )
),

weekly_values AS (
  SELECT matchup_period, team_id, category, value
  FROM finished_weeks
  UNPIVOT INCLUDE NULLS (
    value FOR category IN (fg_pct, ft_pct, fg3m, fg3_pct, reb, ast, stl, blk, pts)
  )
),

-- Per team-week-category: share of the other teams beaten (ties and NULLs half).
weekly_win_rates AS (
  SELECT
    a.team_id,
    a.category,
    a.matchup_period,
    (COUNTIF(a.value > b.value)
      + 0.5 * (COUNT(*) - COUNTIF(a.value > b.value) - COUNTIF(a.value < b.value))
    ) / COUNT(*) AS win_rate
  FROM weekly_values AS a
  JOIN weekly_values AS b
    ON a.matchup_period = b.matchup_period
   AND a.category = b.category
   AND a.team_id != b.team_id
  GROUP BY a.team_id, a.category, a.matchup_period
),

results AS (
  SELECT
    s.snapshot_date,
    CAST(NULL AS STRING) AS stat_window,
    'results' AS lens,
    v.team_id,
    t.team_name,
    v.category,
    v.value,
    r.win_rate
  FROM season_values AS v
  CROSS JOIN status AS s
  LEFT JOIN latest_teams AS t
    ON t.team_id = v.team_id
  LEFT JOIN (
    SELECT team_id, category, AVG(win_rate) AS win_rate
    FROM weekly_win_rates
    GROUP BY team_id, category
  ) AS r
    ON r.team_id = v.team_id
   AND r.category = v.category
),

combined AS (
  SELECT * FROM roster
  UNION ALL
  SELECT * FROM results
)

SELECT
  *,
  RANK() OVER ordered AS rank,
  LAG(value) OVER ordered - value AS gap_above,
  value - LEAD(value) OVER ordered AS gap_below
FROM combined
WINDOW ordered AS (
  PARTITION BY snapshot_date, stat_window, lens, category ORDER BY value DESC
);
