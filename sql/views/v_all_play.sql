-- Step 5: self-joins every team to every other team in the same week; counts
-- category wins in each simulated matchup. Feeds v_power_rankings and v_luck.
--
-- Grain: team-week. `pairings` decides each simulated head-to-head (team vs one
-- opponent) on the 9 categories from v_team_week_cats -- higher wins in all of them;
-- this league doesn't score turnovers. The final SELECT rolls those up into the
-- team's all-play record for the week, both as matchups (W/L/T per opponent) and as
-- raw category counts, so downstream views can use either. A NULL percentage (0
-- attempts) can't be compared, so it counts as a tied category. Ties count as half
-- a win in both win percentages.

CREATE OR REPLACE VIEW `fantasy-dash-emk.fantasy.v_all_play` AS
WITH cats AS (
  SELECT season, matchup_period, team_id, category, value
  FROM `fantasy-dash-emk.fantasy.v_team_week_cats`
  UNPIVOT INCLUDE NULLS (
    value FOR category IN (fg_pct, ft_pct, fg3m, fg3_pct, reb, ast, stl, blk, pts)
  )
),

pairings AS (
  SELECT
    a.season,
    a.matchup_period,
    a.team_id,
    b.team_id AS opponent_id,
    COUNTIF(a.value > b.value) AS cat_wins,
    COUNTIF(a.value < b.value) AS cat_losses,
    COUNT(*) - COUNTIF(a.value > b.value) - COUNTIF(a.value < b.value) AS cat_ties
  FROM cats AS a
  JOIN cats AS b
    ON a.season = b.season
   AND a.matchup_period = b.matchup_period
   AND a.category = b.category
   AND a.team_id != b.team_id
  GROUP BY a.season, a.matchup_period, a.team_id, b.team_id
)

SELECT
  season,
  matchup_period,
  team_id,
  COUNTIF(cat_wins > cat_losses) AS ap_wins,
  COUNTIF(cat_wins < cat_losses) AS ap_losses,
  COUNTIF(cat_wins = cat_losses) AS ap_ties,
  SAFE_DIVIDE(
    COUNTIF(cat_wins > cat_losses) + 0.5 * COUNTIF(cat_wins = cat_losses), COUNT(*)
  ) AS ap_win_pct,
  SUM(cat_wins) AS ap_cat_wins,
  SUM(cat_losses) AS ap_cat_losses,
  SUM(cat_ties) AS ap_cat_ties,
  SAFE_DIVIDE(
    SUM(cat_wins) + 0.5 * SUM(cat_ties), SUM(cat_wins + cat_losses + cat_ties)
  ) AS ap_cat_win_pct
FROM pairings
GROUP BY season, matchup_period, team_id;
