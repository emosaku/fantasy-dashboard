-- Each pool player's health (ESPN status, return date, outlook) and durability:
-- average games played over the last 3 seasons he was in the NBA, and each season.
CREATE OR REPLACE VIEW `{project}.{dataset}.v_player_profile` AS
WITH history AS (
  SELECT
    d.league_id,
    d.player_id,
    AVG(h.games_played) AS avg_games_played,
    COUNT(h.games_played) AS seasons_counted,
    MAX(IF(h.history_season = d.season - 1, h.games_played, NULL)) AS gp_last_season,
    MAX(IF(h.history_season = d.season - 2, h.games_played, NULL)) AS gp_2_seasons_ago,
    MAX(IF(h.history_season = d.season - 3, h.games_played, NULL)) AS gp_3_seasons_ago
  FROM `{project}.{dataset}.player_details` AS d
  JOIN `{project}.{dataset}.player_seasons` AS h
    ON h.player_id = d.player_id
   AND h.history_season BETWEEN d.season - 3 AND d.season - 1
  GROUP BY d.league_id, d.player_id
)

SELECT
  d.league_id,
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
FROM `{project}.{dataset}.player_details` AS d
LEFT JOIN history AS h
  ON h.league_id = d.league_id AND h.player_id = d.player_id;
