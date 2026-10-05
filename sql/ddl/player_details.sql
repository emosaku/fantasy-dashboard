-- Added in Step 6: player_details table -- grain: snapshot_date x player.
--
-- Everything ESPN reports about each pool player's health that day: the injured
-- flag, injury status (ACTIVE / DAY_TO_DAY / OUT), expected return date (often NULL;
-- ESPN rarely fills it), and the written season outlook, which is where injury
-- context usually lives. ESPN doesn't publish injury type or body part. Shown with
-- each player in the Trade Analyzer's mock trade (v_player_profile).
--
-- Natural key for Step 4's MERGE: (season, snapshot_date, player_id).

CREATE TABLE IF NOT EXISTS `fantasy-dash-emk.fantasy.player_details` (
  snapshot_date DATE NOT NULL,
  season INT64 NOT NULL,
  player_id INT64 NOT NULL,
  injured BOOL,
  injury_status STRING,
  expected_return_date DATE,
  season_outlook STRING,
  ingested_at TIMESTAMP NOT NULL
)
PARTITION BY snapshot_date
CLUSTER BY player_id;
