-- Step 5: pivots matchup_categories to one row per team-week; recomputes FG%/FT%
-- from makes and attempts (never average stored percentages directly). Feeds
-- the Compare page.
--
-- Carries exactly this league's 9 scoring categories -- FG%, FT%, 3PM, 3PT%, REB,
-- AST, STL, BLK, PTS -- plus the makes/attempts behind the three percentages, so
-- season-level views can recompute SUM(makes)/SUM(attempts) instead of averaging
-- weekly percentages. ESPN's stored FG%/FT%/3PT% rows are ignored on purpose.
-- SAFE_DIVIDE leaves a percentage NULL on 0 attempts (e.g. before any games).

CREATE OR REPLACE VIEW `fantasy-dash-emk.fantasy.v_team_week_cats` AS
WITH wide AS (
  SELECT
    season,
    matchup_period,
    team_id,
    opponent_id,
    MAX(IF(category = 'FGM', value, NULL)) AS fgm,
    MAX(IF(category = 'FGA', value, NULL)) AS fga,
    MAX(IF(category = 'FTM', value, NULL)) AS ftm,
    MAX(IF(category = 'FTA', value, NULL)) AS fta,
    MAX(IF(category = '3PM', value, NULL)) AS fg3m,
    MAX(IF(category = '3PA', value, NULL)) AS fg3a,
    MAX(IF(category = 'REB', value, NULL)) AS reb,
    MAX(IF(category = 'AST', value, NULL)) AS ast,
    MAX(IF(category = 'STL', value, NULL)) AS stl,
    MAX(IF(category = 'BLK', value, NULL)) AS blk,
    MAX(IF(category = 'PTS', value, NULL)) AS pts
  FROM `fantasy-dash-emk.fantasy.matchup_categories`
  GROUP BY season, matchup_period, team_id, opponent_id
)
SELECT
  season,
  matchup_period,
  team_id,
  opponent_id,
  SAFE_DIVIDE(fgm, fga) AS fg_pct,
  SAFE_DIVIDE(ftm, fta) AS ft_pct,
  fg3m,
  SAFE_DIVIDE(fg3m, fg3a) AS fg3_pct,
  reb,
  ast,
  stl,
  blk,
  pts,
  fgm,
  fga,
  ftm,
  fta,
  fg3a
FROM wide;
