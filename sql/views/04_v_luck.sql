-- Luck: actual win % minus all-play win %, at the level the league scores. Most
-- Categories: a week is one W/L/T, compared with all-play matchup win %. Each Category:
-- a week is a category record (6-3-0), compared with all-play category win %. Actual
-- results are ESPN's own per-category verdicts. luck_week is one week; luck is
-- season-to-date through it.
CREATE OR REPLACE VIEW `{project}.{dataset}.v_luck` AS
WITH actual AS (
  SELECT
    m.league_id,
    m.season,
    m.matchup_period,
    m.team_id,
    m.opponent_id,
    COUNTIF(m.result = 'W') AS cat_wins,
    COUNTIF(m.result = 'L') AS cat_losses,
    COUNTIF(m.result = 'T') AS cat_ties
  FROM `{project}.{dataset}.matchup_categories` AS m
  JOIN `{project}.{dataset}.league_categories` AS c
    ON c.league_id = m.league_id AND c.category = m.category
  GROUP BY 1, 2, 3, 4, 5
),

weekly AS (
  SELECT
    a.*,
    s.scoring_type,
    CASE
      WHEN a.cat_wins > a.cat_losses THEN 'W'
      WHEN a.cat_wins < a.cat_losses THEN 'L'
      ELSE 'T'
    END AS actual_result,
    IF(
      s.scoring_type = 'H2H_EACH_CATEGORY',
      COALESCE(SAFE_DIVIDE(a.cat_wins + 0.5 * a.cat_ties, a.cat_wins + a.cat_losses + a.cat_ties), 0.5),
      CASE WHEN a.cat_wins > a.cat_losses THEN 1.0 WHEN a.cat_wins < a.cat_losses THEN 0.0 ELSE 0.5 END
    ) AS actual_score,
    ap.ap_wins,
    ap.ap_losses,
    ap.ap_ties,
    IF(s.scoring_type = 'H2H_EACH_CATEGORY', ap.ap_cat_win_pct, ap.ap_win_pct) AS ap_win_pct
  FROM actual AS a
  JOIN `{project}.{dataset}.league_settings` AS s
    USING (league_id)
  JOIN `{project}.{dataset}.v_all_play` AS ap
    ON ap.league_id = a.league_id AND ap.matchup_period = a.matchup_period
   AND ap.team_id = a.team_id
)

SELECT
  w.league_id,
  w.season,
  w.matchup_period,
  w.team_id,
  t.team_name,
  w.opponent_id,
  o.team_name AS opponent_name,
  w.cat_wins,
  w.cat_losses,
  w.cat_ties,
  w.actual_result,
  w.ap_wins,
  w.ap_losses,
  w.ap_ties,
  w.ap_win_pct,
  w.actual_score - w.ap_win_pct AS luck_week,
  AVG(w.actual_score) OVER to_date AS actual_win_pct_to_date,
  AVG(w.ap_win_pct) OVER to_date AS ap_win_pct_to_date,
  AVG(w.actual_score) OVER to_date - AVG(w.ap_win_pct) OVER to_date AS luck
FROM weekly AS w
LEFT JOIN `{project}.{dataset}.teams` AS t
  ON t.league_id = w.league_id AND t.team_id = w.team_id
LEFT JOIN `{project}.{dataset}.teams` AS o
  ON o.league_id = w.league_id AND o.team_id = w.opponent_id
WINDOW to_date AS (PARTITION BY w.league_id, w.season, w.team_id ORDER BY w.matchup_period);
