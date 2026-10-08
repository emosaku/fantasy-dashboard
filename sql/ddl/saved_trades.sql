-- Trades managers saved in the Trade Analyzer (app/saved_store.py): one row per
-- person, team and trade; `record` is the trade as JSON (app/saved_trades.py). The
-- dashboard's service account may write this table, and only this one:
--   bq add-iam-policy-binding \
--     --member=serviceAccount:dashboard-sa@fantasy-dash-emk.iam.gserviceaccount.com \
--     --role=roles/bigquery.dataEditor fantasy-dash-emk:fantasy.saved_trades
CREATE TABLE IF NOT EXISTS `fantasy-dash-emk.fantasy.saved_trades` (
  username STRING NOT NULL,           -- the manager's login
  team_id INT64 NOT NULL,             -- the team the trade was saved for
  trade_id STRING NOT NULL,           -- the same move always has the same id
  record STRING NOT NULL,             -- the trade as JSON
  saved_at TIMESTAMP NOT NULL
);
