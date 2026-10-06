-- All-play: every team against every other team in its league, each week, on the
-- league's categories (`score`, so turnovers count lower-is-better). A simulated
-- matchup is a W/L/T on category count. Grain: league x team x week. Both the
-- matchup-level and the category-level records are kept: Most Categories leagues
-- rank on the first, Each Category leagues on the second. Ties count half.
CREATE OR REPLACE VIEW `{project}.{dataset}.v_all_play` AS
WITH cats AS (
  SELECT league_id, season, matchup_period, team_id, category, score
  FROM `{project}.{dataset}.v_team_week_cats`
),

pairings AS (
  SELECT
    a.league_id,
    a.season,
    a.matchup_period,
    a.team_id,
    b.team_id AS opponent_id,
    COUNTIF(a.score > b.score) AS cat_wins,
    COUNTIF(a.score < b.score) AS cat_losses,
    COUNT(*) - COUNTIF(a.score > b.score) - COUNTIF(a.score < b.score) AS cat_ties
  FROM cats AS a
  JOIN cats AS b
    ON a.league_id = b.league_id
   AND a.matchup_period = b.matchup_period
   AND a.category = b.category
   AND a.team_id != b.team_id
  GROUP BY 1, 2, 3, 4, 5
)

SELECT
  league_id,
  season,
  matchup_period,
  team_id,
  COUNTIF(cat_wins > cat_losses) AS ap_wins,
  COUNTIF(cat_wins < cat_losses) AS ap_losses,
  COUNTIF(cat_wins = cat_losses) AS ap_ties,
  SAFE_DIVIDE(COUNTIF(cat_wins > cat_losses) + 0.5 * COUNTIF(cat_wins = cat_losses), COUNT(*))
    AS ap_win_pct,
  SUM(cat_wins) AS ap_cat_wins,
  SUM(cat_losses) AS ap_cat_losses,
  SUM(cat_ties) AS ap_cat_ties,
  SAFE_DIVIDE(SUM(cat_wins) + 0.5 * SUM(cat_ties), SUM(cat_wins + cat_losses + cat_ties))
    AS ap_cat_win_pct
FROM pairings
GROUP BY league_id, season, matchup_period, team_id;
