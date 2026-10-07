-- ESPN's picks for the league's draft, once ESPN shares them (after the draft; live,
-- if it ever does). Picks entered on the Draft page live in Firestore, not here.
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.draft_picks` (
  league_id INT64 NOT NULL,
  season INT64 NOT NULL,
  overall INT64 NOT NULL,
  round INT64 NOT NULL,
  round_pick INT64 NOT NULL,
  team_id INT64 NOT NULL,
  player_id INT64 NOT NULL,
  keeper BOOL NOT NULL,
  ingested_at TIMESTAMP NOT NULL
)
CLUSTER BY league_id;
