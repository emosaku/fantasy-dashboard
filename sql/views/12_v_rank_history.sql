-- Each team's rank in each category, day by day, with its change since the same day a
-- week before (positive = moved up): the week-over-week arrows on the Players page.
-- From the daily snapshots (snap_category_ranks); categories leagues only.
CREATE OR REPLACE VIEW `{project}.{dataset}.v_rank_history` AS
SELECT
  c.snapshot_date,
  c.league_id,
  c.season,
  c.stat_window,
  c.lens,
  c.team_id,
  c.category,
  c.value,
  c.rank,
  w.rank AS rank_week_ago,
  w.rank - c.rank AS rank_change
FROM `{project}.{dataset}.snap_category_ranks` AS c
LEFT JOIN `{project}.{dataset}.snap_category_ranks` AS w
  ON w.league_id = c.league_id
 AND w.team_id = c.team_id
 AND w.category = c.category
 AND w.lens = c.lens
 AND w.stat_window IS NOT DISTINCT FROM c.stat_window
 AND w.snapshot_date = DATE_SUB(c.snapshot_date, INTERVAL 7 DAY);
