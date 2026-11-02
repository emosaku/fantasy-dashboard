-- Each team's record and standing, day by day, with the standing a week before and the
-- change (positive = moved up). From snap_standings; both formats.
CREATE OR REPLACE VIEW `{project}.{dataset}.v_standing_history` AS
SELECT
  s.snapshot_date,
  s.league_id,
  s.season,
  s.team_id,
  s.team_name,
  s.wins,
  s.losses,
  s.ties,
  s.points_for,
  s.standing,
  w.standing AS standing_week_ago,
  w.standing - s.standing AS standing_change
FROM `{project}.{dataset}.snap_standings` AS s
LEFT JOIN `{project}.{dataset}.snap_standings` AS w
  ON w.league_id = s.league_id
 AND w.team_id = s.team_id
 AND w.snapshot_date = DATE_SUB(s.snapshot_date, INTERVAL 7 DAY);
