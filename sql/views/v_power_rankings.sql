-- Step 5: season totals from v_all_play -- all-play win %, category win %, rank.
-- Feeds the Power Rankings page.
--
-- Grain: team x matchup_period, where every number is season-to-date *through* that
-- week. That one shape serves both of the page's visuals: filter to one week for the
-- ranked table (the latest week is the season total), or keep every week for the
-- rank-over-time line chart. Ranked on all-play win %, then all-play category
-- win % as the tiebreak. Team names come from each team's latest snapshot, so a
-- renamed team shows its current name across every week.

CREATE OR REPLACE VIEW `fantasy-dash-emk.fantasy.v_power_rankings` AS
WITH latest_teams AS (
  SELECT season, team_id, team_name
  FROM `fantasy-dash-emk.fantasy.teams`
  QUALIFY ROW_NUMBER() OVER (PARTITION BY season, team_id ORDER BY snapshot_date DESC) = 1
),

to_date AS (
  SELECT
    season,
    matchup_period,
    team_id,
    SUM(ap_wins) OVER w AS ap_wins,
    SUM(ap_losses) OVER w AS ap_losses,
    SUM(ap_ties) OVER w AS ap_ties,
    SUM(ap_cat_wins) OVER w AS ap_cat_wins,
    SUM(ap_cat_losses) OVER w AS ap_cat_losses,
    SUM(ap_cat_ties) OVER w AS ap_cat_ties
  FROM `fantasy-dash-emk.fantasy.v_all_play`
  WINDOW w AS (PARTITION BY season, team_id ORDER BY matchup_period)
),

pcts AS (
  SELECT
    *,
    SAFE_DIVIDE(ap_wins + 0.5 * ap_ties, ap_wins + ap_losses + ap_ties) AS ap_win_pct,
    SAFE_DIVIDE(
      ap_cat_wins + 0.5 * ap_cat_ties, ap_cat_wins + ap_cat_losses + ap_cat_ties
    ) AS ap_cat_win_pct
  FROM to_date
)

SELECT
  p.season,
  p.matchup_period,
  p.team_id,
  t.team_name,
  RANK() OVER (
    PARTITION BY p.season, p.matchup_period
    ORDER BY p.ap_win_pct DESC, p.ap_cat_win_pct DESC
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
LEFT JOIN latest_teams AS t
  ON t.season = p.season
 AND t.team_id = p.team_id;
