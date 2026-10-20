-- LeagueLabWhop: every NBA player's line in every game, from BallDontLie ALL-STAR
-- (docs/whopDocs/projections.md). Shared by every league, not per league: the source
-- of our own projections and stat windows. Stat columns use BallDontLie's names
-- (BigQuery columns can't start with a digit); ingest/projections/games.py maps them
-- to League Lab's (fg3m -> 3PM, tov -> TO ...). A row with min = 0 is a game he
-- didn't play. Grain: player x game.
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.nba_player_games` (
  player_id INT64 NOT NULL,           -- BallDontLie's id (nba_players maps it to ESPN's)
  game_id INT64 NOT NULL,
  season INT64 NOT NULL,              -- by end year, as ESPN names it: 2027 = 2026-27
  game_date DATE NOT NULL,
  team STRING,                        -- the team he played for that night
  min FLOAT64, pts FLOAT64, reb FLOAT64, oreb FLOAT64, dreb FLOAT64, ast FLOAT64,
  stl FLOAT64, blk FLOAT64, tov FLOAT64, fgm FLOAT64, fga FLOAT64, fg3m FLOAT64,
  fg3a FLOAT64, ftm FLOAT64, fta FLOAT64,
  ingested_at TIMESTAMP NOT NULL
)
PARTITION BY RANGE_BUCKET(season, GENERATE_ARRAY(2000, 2100, 1))
CLUSTER BY player_id;
