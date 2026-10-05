-- Added in Step 6: league_status table -- grain: season x snapshot_date.
--
-- One row per ingest run: where the season stands that day. Feeds the season
-- projection (app/analysis/projection.py), which needs to know which matchup periods
-- are finished (actual results) and how many are left (projected). Neither is derivable from the
-- other tables: matchup_categories only has periods up to the current one, and
-- includes the current one while it's still in progress.
--
-- reg_season_matchup_periods is ESPN's settings.reg_season_count -- the number of
-- regular-season matchup periods (playoff periods come after it).
--
-- Natural key for Step 4's MERGE: (season, snapshot_date).

CREATE TABLE IF NOT EXISTS `fantasy-dash-emk.fantasy.league_status` (
  snapshot_date DATE NOT NULL,
  season INT64 NOT NULL,
  current_matchup_period INT64 NOT NULL,
  reg_season_matchup_periods INT64 NOT NULL,
  playoff_team_count INT64,
  ingested_at TIMESTAMP NOT NULL
)
PARTITION BY snapshot_date;
