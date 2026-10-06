-- Every team ranked in every category of its league, through two lenses:
--   roster  -- team z totals per stat window (forward-looking)
--   results -- finished weeks: count categories average the weekly value; ratios
--              pool the two totals over the weeks; win_rate = share of the other
--              teams beaten in that category, averaged over weeks
-- Rank 1 is best, on `score` (lower-is-better categories flipped); `value` is what's
-- shown. Ties share a rank. gap_above / gap_below: distance (in score) to the
-- next-better / next-worse team.
CREATE OR REPLACE VIEW `{project}.{dataset}.v_category_ranks` AS
WITH roster AS (
  SELECT
    league_id, season, stat_window, 'roster' AS lens, team_id, team_name, category,
    team_z AS value, team_z AS score, CAST(NULL AS FLOAT64) AS win_rate
  FROM `{project}.{dataset}.v_team_category_z`
),

finished AS (
  SELECT w.*
  FROM `{project}.{dataset}.v_team_week_cats` AS w
  JOIN `{project}.{dataset}.league_settings` AS s
    USING (league_id)
  WHERE w.matchup_period < s.current_matchup_period
),

season_values AS (
  SELECT
    league_id, season, team_id, category,
    IF(ANY_VALUE(kind) = 'ratio', SAFE_DIVIDE(SUM(num), SUM(den)), AVG(value)) AS value,
    ANY_VALUE(lower_is_better) AS lower_is_better
  FROM finished
  GROUP BY 1, 2, 3, 4
),

weekly_win_rates AS (
  SELECT
    a.league_id, a.team_id, a.category, a.matchup_period,
    (COUNTIF(a.score > b.score)
      + 0.5 * (COUNT(*) - COUNTIF(a.score > b.score) - COUNTIF(a.score < b.score))
    ) / COUNT(*) AS win_rate
  FROM finished AS a
  JOIN finished AS b
    ON a.league_id = b.league_id AND a.matchup_period = b.matchup_period
   AND a.category = b.category AND a.team_id != b.team_id
  GROUP BY 1, 2, 3, 4
),

results AS (
  SELECT
    v.league_id, v.season, CAST(NULL AS STRING) AS stat_window, 'results' AS lens,
    v.team_id, t.team_name, v.category, v.value,
    IF(v.lower_is_better, -v.value, v.value) AS score,
    r.win_rate
  FROM season_values AS v
  LEFT JOIN `{project}.{dataset}.teams` AS t
    ON t.league_id = v.league_id AND t.team_id = v.team_id
  LEFT JOIN (
    SELECT league_id, team_id, category, AVG(win_rate) AS win_rate
    FROM weekly_win_rates
    GROUP BY 1, 2, 3
  ) AS r
    ON r.league_id = v.league_id AND r.team_id = v.team_id AND r.category = v.category
),

combined AS (
  SELECT * FROM roster
  UNION ALL
  SELECT * FROM results
)

SELECT
  * EXCEPT (score),
  RANK() OVER ordered AS rank,
  LAG(score) OVER ordered - score AS gap_above,
  score - LEAD(score) OVER ordered AS gap_below
FROM combined
WINDOW ordered AS (
  PARTITION BY league_id, stat_window, lens, category ORDER BY score DESC
);
