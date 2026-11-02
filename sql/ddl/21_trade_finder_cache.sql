-- LeagueLabWhop: the trade finder's default search per team, kept so the React app's
-- Trades page opens instantly (docs/reactDocs/phase1-api.md). Written by the API: by
-- api/precompute.py after each morning's refresh, or on the first request after a data
-- load. A row is current only for its data_version (the league's last_ingested_at);
-- an older one is replaced, never read. deals: the API's JSON rows. Grain: league x
-- team x stat window.
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.trade_finder_cache` (
  league_id INT64 NOT NULL,
  team_id INT64 NOT NULL,
  stat_window STRING NOT NULL,
  data_version STRING NOT NULL,      -- last_ingested_at, ISO 8601
  computed_at TIMESTAMP NOT NULL,
  deals STRING NOT NULL              -- JSON array
)
CLUSTER BY league_id, team_id;
