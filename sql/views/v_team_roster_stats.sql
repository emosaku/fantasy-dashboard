-- Step 5 (added): joins each team's current roster to every player's per-game stat
-- line. Raw per-game averages, deliberately not z-scored like v_roster_strength --
-- a trade's before/after/delta comparison needs plain numbers, not league-relative
-- ones. Feeds the Trade Analyzer page.
--
-- Grain: player x stat_window, for the latest roster snapshot only. Every stat window
-- is included, so the page (and v_roster_strength) can switch windows by filtering.
-- Before the season starts only 'projected' exists, which is why it's carried at all.
-- Makes and attempts ride along with each percentage: when the app sums players
-- into a roster total, it must recompute SUM(makes) / SUM(attempts), never average
-- the players' percentages. A player with no stats in a window has no row for it.

CREATE OR REPLACE VIEW `fantasy-dash-emk.fantasy.v_team_roster_stats` AS
WITH latest_roster AS (
  SELECT *
  FROM `fantasy-dash-emk.fantasy.rosters`
  WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM `fantasy-dash-emk.fantasy.rosters`)
),

latest_teams AS (
  SELECT season, team_id, team_name
  FROM `fantasy-dash-emk.fantasy.teams`
  QUALIFY ROW_NUMBER() OVER (PARTITION BY season, team_id ORDER BY snapshot_date DESC) = 1
)

SELECT
  r.snapshot_date,
  r.season,
  r.team_id,
  t.team_name,
  r.player_id,
  r.player_name,
  r.position,
  r.lineup_slot,
  r.injury_status,
  s.stat_window,
  SAFE_DIVIDE(s.fgm, s.fga) AS fg_pct,
  SAFE_DIVIDE(s.ftm, s.fta) AS ft_pct,
  s.fg3m,
  SAFE_DIVIDE(s.fg3m, s.fg3a) AS fg3_pct,
  s.reb,
  s.ast,
  s.stl,
  s.blk,
  s.pts,
  s.fgm,
  s.fga,
  s.ftm,
  s.fta,
  s.fg3a
FROM latest_roster AS r
JOIN `fantasy-dash-emk.fantasy.player_stats` AS s
  ON s.season = r.season
 AND s.snapshot_date = r.snapshot_date
 AND s.player_id = r.player_id
LEFT JOIN latest_teams AS t
  ON t.season = r.season
 AND t.team_id = r.team_id;
