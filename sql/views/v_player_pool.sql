-- Added in Step 6 (Category Rankings + Trade & Waiver Analyzer): the player pool the
-- z-scores are measured against.
--
-- Grain: snapshot_date x stat_window x player, for the latest snapshot. Every rostered
-- player plus the day's top free agents (free_agents table), joined to their per-game
-- stat lines. team_id is the owner, NULL for a free agent. Including the free agents
-- matters: league means and spreads then reflect who's realistically available, and
-- the waiver analyzer can score pickups on the same scale as rostered players.
--
-- expected_return_date is ESPN's estimate for an injured rostered player (often
-- NULL); the injury-aware season projection uses it when present.
--
-- A player with no stat line in a window (e.g. a free agent ESPN hasn't projected)
-- has no row for that window. Missing counting stats are kept as NULL here;
-- v_player_z treats them as 0.

CREATE OR REPLACE VIEW `fantasy-dash-emk.fantasy.v_player_pool` AS
WITH latest AS (
  SELECT MAX(snapshot_date) AS snapshot_date FROM `fantasy-dash-emk.fantasy.rosters`
),

pool AS (
  SELECT
    r.snapshot_date,
    r.season,
    r.player_id,
    r.player_name,
    r.position,
    CAST(NULL AS STRING) AS pro_team,
    r.team_id,
    r.lineup_slot,
    r.injury_status,
    r.expected_return_date
  FROM `fantasy-dash-emk.fantasy.rosters` AS r
  JOIN latest USING (snapshot_date)

  UNION ALL

  SELECT
    f.snapshot_date,
    f.season,
    f.player_id,
    f.player_name,
    f.position,
    f.pro_team,
    CAST(NULL AS INT64) AS team_id,
    CAST(NULL AS STRING) AS lineup_slot,
    f.injury_status,
    CAST(NULL AS DATE) AS expected_return_date
  FROM `fantasy-dash-emk.fantasy.free_agents` AS f
  JOIN latest USING (snapshot_date)
)

SELECT
  p.snapshot_date,
  p.season,
  s.stat_window,
  p.player_id,
  p.player_name,
  p.position,
  p.pro_team,
  p.team_id,
  p.team_id IS NULL AS is_free_agent,
  COALESCE(p.lineup_slot = 'IR', FALSE) AS is_ir,
  p.lineup_slot,
  p.injury_status,
  p.expected_return_date,
  s.gp,
  s.pts,
  s.reb,
  s.ast,
  s.stl,
  s.blk,
  s.fg3m,
  s.fg3a,
  s.fgm,
  s.fga,
  s.ftm,
  s.fta
FROM pool AS p
JOIN `fantasy-dash-emk.fantasy.player_stats` AS s
  ON s.season = p.season
 AND s.snapshot_date = p.snapshot_date
 AND s.player_id = p.player_id;
