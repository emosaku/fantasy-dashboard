-- League Lab: each league's scoring categories, read from its ESPN settings. Every view
-- and the dashboard take their category list from here, never from constants.
--   kind = 'count': the category is one per-game stat (num_stat = the stat itself)
--   kind = 'ratio': num_stat / den_stat (FG% = FGM / FGA, A/TO = AST / TO); always
--                   recomputed from the two totals, never averaged
--   lower_is_better: ESPN's isReverseItem (turnovers). Views flip its sign so "higher
--                    is better" holds everywhere downstream.
-- Grain: league x category. Current state.
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.league_categories` (
  league_id INT64 NOT NULL,
  season INT64 NOT NULL,
  category STRING NOT NULL,           -- ESPN's abbreviation: PTS, 3PT%, TO, A/TO ...
  kind STRING NOT NULL,               -- count | ratio
  num_stat STRING NOT NULL,
  den_stat STRING,
  lower_is_better BOOL NOT NULL,
  display_order INT64 NOT NULL,
  ingested_at TIMESTAMP NOT NULL
)
CLUSTER BY league_id;
