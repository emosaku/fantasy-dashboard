-- LeagueLabWhop: daily league snapshots, the history only League Lab has
-- (docs/whopDocs/moat.md, docs/whopDocs/snapshots.md). Each morning's refresh keeps a
-- dated copy of what the current-state tables overwrite: who was on each roster,
-- the standings, every team's category ranks (tiers come from these), and every
-- player's value in the league. Written by ingest (materialize.snapshot_statements):
-- re-running a day replaces that day's rows for the league, so a day is never
-- doubled. Never reshaped or dropped without a migration that keeps the rows.
-- Not copied, because it can be rebuilt for any date: NBA stat lines
-- (nba_player_games), our projections (projections, one row set per run), weekly
-- results, power rankings and luck (matchup tables, kept per week), transactions.
-- snapshot_date: the day of the refresh in US Eastern time (the NBA's calendar).

-- Grain: league x day x team x player.
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.snap_rosters` (
  snapshot_date DATE NOT NULL,
  league_id INT64 NOT NULL,
  season INT64 NOT NULL,
  team_id INT64 NOT NULL,
  player_id INT64 NOT NULL,
  player_name STRING,
  lineup_slot STRING,
  injury_status STRING,
  pro_team STRING
)
PARTITION BY snapshot_date
CLUSTER BY league_id, team_id;

-- Grain: league x day x team.
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.snap_standings` (
  snapshot_date DATE NOT NULL,
  league_id INT64 NOT NULL,
  season INT64 NOT NULL,
  team_id INT64 NOT NULL,
  team_name STRING,
  owner STRING,
  wins INT64,
  losses INT64,
  ties INT64,
  points_for FLOAT64,
  points_against FLOAT64,
  standing INT64
)
PARTITION BY snapshot_date
CLUSTER BY league_id, team_id;

-- Categories leagues. Grain: league x day x window x lens x team x category.
-- Lock / Swing / Punt tiers are computed from rank and the gaps (app/analysis/weights.py).
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.snap_category_ranks` (
  snapshot_date DATE NOT NULL,
  league_id INT64 NOT NULL,
  season INT64 NOT NULL,
  stat_window STRING,
  lens STRING,
  team_id INT64 NOT NULL,
  category STRING NOT NULL,
  value FLOAT64,
  win_rate FLOAT64,
  rank INT64,
  gap_above FLOAT64,
  gap_below FLOAT64
)
PARTITION BY snapshot_date
CLUSTER BY league_id, team_id;

-- Categories leagues: each pool player's per-game value and z-score per category,
-- season so far and projected. Grain: league x day x window x player x category.
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.snap_player_z` (
  snapshot_date DATE NOT NULL,
  league_id INT64 NOT NULL,
  season INT64 NOT NULL,
  stat_window STRING NOT NULL,
  player_id INT64 NOT NULL,
  team_id INT64,                     -- NULL: a free agent that day
  category STRING NOT NULL,
  value FLOAT64,
  z FLOAT64
)
PARTITION BY snapshot_date
CLUSTER BY league_id, player_id;

-- Points leagues: each pool player's fantasy points per game, season so far and
-- projected. Grain: league x day x window x player.
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.snap_player_points` (
  snapshot_date DATE NOT NULL,
  league_id INT64 NOT NULL,
  season INT64 NOT NULL,
  stat_window STRING NOT NULL,
  player_id INT64 NOT NULL,
  fp_per_game FLOAT64,
  games FLOAT64
)
PARTITION BY snapshot_date
CLUSTER BY league_id, player_id;
