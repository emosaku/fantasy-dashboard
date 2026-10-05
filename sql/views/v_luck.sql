-- Step 5: actual win % minus all-play win % from v_all_play; positive means lucky.
-- Feeds the Matchups and Luck page.
--
-- Grain: team x matchup_period. The league is H2H Most Categories, so a week is one
-- W/L/T: whoever wins more of the 9 scoring categories. The actual result is
-- rebuilt from ESPN's own per-category `result` (ESPN's verdict, not a
-- recomputation), and it's compared with v_all_play's matchup-level win % -- the
-- record the team would have had against every opponent that week. Ties count as
-- half a win on both sides.
--
-- luck_week is that week alone (e.g. a narrow win in a week the team would have
-- beaten only 3 of 13 teams is +0.77); luck is the season-to-date total through that
-- week, which is the number the luck bar chart shows.

CREATE OR REPLACE VIEW `fantasy-dash-emk.fantasy.v_luck` AS
WITH latest_teams AS (
  SELECT season, team_id, team_name
  FROM `fantasy-dash-emk.fantasy.teams`
  QUALIFY ROW_NUMBER() OVER (PARTITION BY season, team_id ORDER BY snapshot_date DESC) = 1
),

actual AS (
  SELECT
    season,
    matchup_period,
    team_id,
    opponent_id,
    COUNTIF(result = 'W') AS cat_wins,
    COUNTIF(result = 'L') AS cat_losses,
    COUNTIF(result = 'T') AS cat_ties
  FROM `fantasy-dash-emk.fantasy.matchup_categories`
  WHERE category IN ('FG%', 'FT%', '3PM', '3PT%', 'REB', 'AST', 'STL', 'BLK', 'PTS')
  GROUP BY season, matchup_period, team_id, opponent_id
),

weekly AS (
  SELECT
    a.season,
    a.matchup_period,
    a.team_id,
    a.opponent_id,
    a.cat_wins,
    a.cat_losses,
    a.cat_ties,
    CASE
      WHEN a.cat_wins > a.cat_losses THEN 'W'
      WHEN a.cat_wins < a.cat_losses THEN 'L'
      ELSE 'T'
    END AS actual_result,
    CASE
      WHEN a.cat_wins > a.cat_losses THEN 1.0
      WHEN a.cat_wins < a.cat_losses THEN 0.0
      ELSE 0.5
    END AS actual_score,
    ap.ap_wins,
    ap.ap_losses,
    ap.ap_ties,
    ap.ap_win_pct
  FROM actual AS a
  JOIN `fantasy-dash-emk.fantasy.v_all_play` AS ap
    ON ap.season = a.season
   AND ap.matchup_period = a.matchup_period
   AND ap.team_id = a.team_id
)

SELECT
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
LEFT JOIN latest_teams AS t
  ON t.season = w.season
 AND t.team_id = w.team_id
LEFT JOIN latest_teams AS o
  ON o.season = w.season
 AND o.team_id = w.opponent_id
WINDOW to_date AS (PARTITION BY w.season, w.team_id ORDER BY w.matchup_period);
