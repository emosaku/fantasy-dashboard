-- Step 3: matchup_categories table -- grain: matchup_period x team x category.
--
-- Long format (one row per category, not one column per category) so adding a 10th
-- scoring category later is a config change, not a schema migration. `value` is
-- always a raw make/attempt count or counting stat, never a precomputed percentage --
-- FG%/FT%/3PT% get recomputed in SQL as SUM(makes)/SUM(attempts) (v_team_week_cats,
-- Step 5), since averaging percentages directly gives wrong answers.
--
-- `box_scores()` returns one row with home_team/away_team + home_stats/away_stats;
-- Step 4's ingest transform unpacks each matchup into two rows here, one per side,
-- each carrying its own team_id/opponent_id.
--
-- `result` is nullable: ESPN's real home_stats/away_stats carries attempt-only
-- categories (FGM, FGA, FTM, FTA, 3PA) that don't win/lose on their own -- only the
-- derived FG%/FT%/3PT% rows (and the counting categories) have a real W/L/T result.
--
-- Natural key for Step 4's MERGE: (season, matchup_period, team_id, category).

CREATE TABLE IF NOT EXISTS `fantasy-dash-emk.fantasy.matchup_categories` (
  season INT64 NOT NULL,
  matchup_period INT64 NOT NULL,
  team_id INT64 NOT NULL,
  opponent_id INT64 NOT NULL,
  category STRING NOT NULL,  -- PTS, REB, AST, STL, BLK, 3PM, FGM, FGA, FTM, FTA, TO, FG%, FT%, 3PT%, 3PA
  value FLOAT64 NOT NULL,
  result STRING,  -- W, L, T, or NULL for attempt-only categories -- TO is the one category where lower wins
  ingested_at TIMESTAMP NOT NULL
)
CLUSTER BY matchup_period, team_id;
