-- Each team's value in each of its league's categories, per matchup week (long format).
-- Ratio categories (FG%, A/TO ...) are recomputed from the week's two totals when ESPN
-- reports them; 0 attempts gives NULL, not 0%. `score` flips lower-is-better categories
-- (turnovers) so higher always wins; comparisons downstream use it.
CREATE OR REPLACE VIEW `{project}.{dataset}.v_team_week_cats` AS
WITH box AS (
  SELECT league_id, season, matchup_period, team_id, opponent_id, category, value
  FROM `{project}.{dataset}.matchup_categories`
),

sides AS (
  SELECT DISTINCT league_id, season, matchup_period, team_id, opponent_id FROM box
)

SELECT
  s.league_id,
  s.season,
  s.matchup_period,
  s.team_id,
  s.opponent_id,
  c.category,
  c.kind,
  c.lower_is_better,
  c.display_order,
  n.value AS num,
  d.value AS den,
  v.value AS value,
  IF(c.lower_is_better, -v.value, v.value) AS score
FROM sides AS s
JOIN `{project}.{dataset}.league_categories` AS c
  ON c.league_id = s.league_id
LEFT JOIN box AS own
  ON own.league_id = s.league_id AND own.matchup_period = s.matchup_period
 AND own.team_id = s.team_id AND own.category = c.category
LEFT JOIN box AS n
  ON n.league_id = s.league_id AND n.matchup_period = s.matchup_period
 AND n.team_id = s.team_id AND n.category = c.num_stat
LEFT JOIN box AS d
  ON d.league_id = s.league_id AND d.matchup_period = s.matchup_period
 AND d.team_id = s.team_id AND d.category = c.den_stat
CROSS JOIN UNNEST([STRUCT(
  IF(c.kind = 'ratio' AND n.value IS NOT NULL AND d.value IS NOT NULL,
     SAFE_DIVIDE(n.value, d.value), own.value) AS value
)]) AS v;
