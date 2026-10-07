-- The NBA schedule as one row per team per game, mapped to the league's matchup
-- periods (points leagues: games per week and the daily lineup simulation).
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.pro_schedule` (
  league_id INT64 NOT NULL,
  season INT64 NOT NULL,
  pro_team STRING NOT NULL,           -- espn-api's abbreviation: BOS, LAL ...
  scoring_period INT64 NOT NULL,      -- ESPN's day number (1 = opening night)
  game_date DATE NOT NULL,            -- US Eastern
  matchup_period INT64,               -- NULL after the league's last matchup
  ingested_at TIMESTAMP NOT NULL
)
CLUSTER BY league_id;
