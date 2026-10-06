-- Power rankings: season-to-date all-play through each week, ranked on the measure the
-- league's own scoring uses -- matchup win % for Most Categories, category win % for
-- Each Category. No tiebreak: level teams share a rank.
CREATE OR REPLACE VIEW `{project}.{dataset}.v_power_rankings` AS
WITH to_date AS (
  SELECT
    league_id,
    season,
    matchup_period,
    team_id,
    SUM(ap_wins) OVER w AS ap_wins,
    SUM(ap_losses) OVER w AS ap_losses,
    SUM(ap_ties) OVER w AS ap_ties,
    SUM(ap_cat_wins) OVER w AS ap_cat_wins,
    SUM(ap_cat_losses) OVER w AS ap_cat_losses,
    SUM(ap_cat_ties) OVER w AS ap_cat_ties
  FROM `{project}.{dataset}.v_all_play`
  WINDOW w AS (PARTITION BY league_id, season, team_id ORDER BY matchup_period)
),

pcts AS (
  SELECT
    t.*,
    SAFE_DIVIDE(ap_wins + 0.5 * ap_ties, ap_wins + ap_losses + ap_ties) AS ap_win_pct,
    SAFE_DIVIDE(ap_cat_wins + 0.5 * ap_cat_ties, ap_cat_wins + ap_cat_losses + ap_cat_ties)
      AS ap_cat_win_pct,
    s.scoring_type
  FROM to_date AS t
  JOIN `{project}.{dataset}.league_settings` AS s
    USING (league_id)
)

SELECT
  p.league_id,
  p.season,
  p.matchup_period,
  p.team_id,
  t.team_name,
  RANK() OVER (
    PARTITION BY p.league_id, p.matchup_period
    ORDER BY IF(p.scoring_type = 'H2H_EACH_CATEGORY', p.ap_cat_win_pct, p.ap_win_pct) DESC
  ) AS power_rank,
  p.ap_wins,
  p.ap_losses,
  p.ap_ties,
  p.ap_win_pct,
  p.ap_cat_wins,
  p.ap_cat_losses,
  p.ap_cat_ties,
  p.ap_cat_win_pct
FROM pcts AS p
LEFT JOIN `{project}.{dataset}.teams` AS t
  ON t.league_id = p.league_id AND t.team_id = p.team_id;
