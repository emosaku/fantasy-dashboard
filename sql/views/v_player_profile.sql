-- Added in Step 6: one row per pool player with his durability and health, for the
-- Trade Analyzer's mock trade.
--
-- avg_games_played is the average of his games played over the last 3 completed
-- seasons he was in the NBA for (seasons_counted of them, so a second-year player
-- averages over 1). gp_last_season / gp_2_seasons_ago / gp_3_seasons_ago show each
-- season on its own, NULL where he has no line. Health fields are from the latest
-- snapshot of player_details: ESPN's injured flag, status, expected return date
-- (usually NULL) and season outlook.

CREATE OR REPLACE VIEW `fantasy-dash-emk.fantasy.v_player_profile` AS
WITH latest AS (
  SELECT season, MAX(snapshot_date) AS snapshot_date
  FROM `fantasy-dash-emk.fantasy.player_details`
  WHERE season = (SELECT MAX(season) FROM `fantasy-dash-emk.fantasy.player_details`)
  GROUP BY season
),

history AS (
  SELECT
    h.player_id,
    AVG(h.games_played) AS avg_games_played,
    COUNT(*) AS seasons_counted,
    MAX(IF(h.history_season = l.season - 1, h.games_played, NULL)) AS gp_last_season,
    MAX(IF(h.history_season = l.season - 2, h.games_played, NULL)) AS gp_2_seasons_ago,
    MAX(IF(h.history_season = l.season - 3, h.games_played, NULL)) AS gp_3_seasons_ago
  FROM `fantasy-dash-emk.fantasy.player_seasons` AS h
  JOIN latest AS l
    ON l.season = h.season
  WHERE h.history_season BETWEEN l.season - 3 AND l.season - 1
  GROUP BY h.player_id
)

SELECT
  d.snapshot_date,
  d.season,
  d.player_id,
  d.injured,
  d.injury_status,
  d.expected_return_date,
  d.season_outlook,
  h.avg_games_played,
  h.seasons_counted,
  h.gp_last_season,
  h.gp_2_seasons_ago,
  h.gp_3_seasons_ago
FROM `fantasy-dash-emk.fantasy.player_details` AS d
JOIN latest AS l
  ON l.season = d.season
 AND l.snapshot_date = d.snapshot_date
LEFT JOIN history AS h
  ON h.player_id = d.player_id;
