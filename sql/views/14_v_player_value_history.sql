-- Each pool player's value in his league, day by day, and his rank among the league's
-- pool, with the rank a week before and the change (positive = moved up). Value is
-- his total z across the league's categories (categories leagues, snap_player_z) or
-- his fantasy points per game (points leagues, snap_player_points); season so far and
-- projected.
CREATE OR REPLACE VIEW `{project}.{dataset}.v_player_value_history` AS
WITH player_value AS (
  SELECT snapshot_date, league_id, season, stat_window, player_id, ANY_VALUE(team_id) AS team_id,
         SUM(z) AS value
  FROM `{project}.{dataset}.snap_player_z`
  GROUP BY 1, 2, 3, 4, 5
  UNION ALL
  SELECT snapshot_date, league_id, season, stat_window, player_id,
         CAST(NULL AS INT64) AS team_id, fp_per_game AS value
  FROM `{project}.{dataset}.snap_player_points`
),

ranked AS (
  SELECT
    *,
    RANK() OVER (
      PARTITION BY league_id, snapshot_date, stat_window ORDER BY value DESC
    ) AS value_rank
  FROM player_value
)

SELECT
  r.*,
  w.value_rank AS rank_week_ago,
  w.value_rank - r.value_rank AS rank_change
FROM ranked AS r
LEFT JOIN ranked AS w
  ON w.league_id = r.league_id
 AND w.player_id = r.player_id
 AND w.stat_window = r.stat_window
 AND w.snapshot_date = DATE_SUB(r.snapshot_date, INTERVAL 7 DAY);
