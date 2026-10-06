-- Each roster's combined per-game output per category (non-IR players): count
-- categories summed, ratios from the summed totals; z across the league's teams
-- (lower-is-better flipped). Raw stat windows only -- blended has no raw totals.
CREATE OR REPLACE VIEW `{project}.{dataset}.v_roster_strength` AS
WITH totals AS (
  SELECT
    z.league_id,
    z.season,
    z.stat_window,
    z.team_id,
    t.team_name,
    z.category,
    ANY_VALUE(z.display_order) AS display_order,
    ANY_VALUE(z.lower_is_better) AS lower_is_better,
    COUNT(*) AS players,
    IF(ANY_VALUE(z.kind) = 'ratio', SAFE_DIVIDE(SUM(z.num), SUM(z.den)), SUM(z.num)) AS value
  FROM `{project}.{dataset}.v_player_z` AS z
  LEFT JOIN `{project}.{dataset}.teams` AS t
    ON t.league_id = z.league_id AND t.team_id = z.team_id
  WHERE z.team_id IS NOT NULL
    AND NOT z.is_ir
    AND z.stat_window != 'blended'
  GROUP BY 1, 2, 3, 4, 5, 6
)

SELECT
  * EXCEPT (lower_is_better),
  SAFE_DIVIDE(
    IF(lower_is_better, -value, value) - AVG(IF(lower_is_better, -value, value)) OVER w,
    STDDEV_POP(value) OVER w
  ) AS z
FROM totals
WINDOW w AS (PARTITION BY league_id, stat_window, category);
