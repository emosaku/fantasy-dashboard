"""Entry point for the espn-ingest Cloud Run Job (Step 4).

Builds the espn_api League object from LEAGUE_ID/SEASON/ESPN_S2/SWID (injected as env
vars via Cloud Run's --set-secrets, not read from Secret Manager directly), pulls the
five data sources described in docs/proposal.md (Step 3), and MERGEs each into its
BigQuery target table via a staging table for idempotency.
"""

import os
from datetime import UTC, datetime

from google.cloud import bigquery

from ingest.bigquery_load import merge_load
from ingest.espn_client import build_league
from ingest.transform import (
    transform_matchup_categories,
    transform_player_stats,
    transform_rosters,
    transform_teams,
    transform_transactions,
)


def main() -> None:
    season = int(os.environ["SEASON"])
    project = os.environ.get("GCP_PROJECT_ID", "fantasy-dash-emk")
    dataset = os.environ.get("BIGQUERY_DATASET", "fantasy")
    activity_size = int(os.environ.get("ACTIVITY_SIZE", "50"))

    league = build_league()
    ingested_at = datetime.now(UTC)
    snapshot_date = ingested_at.date()
    current_matchup_period = league.currentMatchupPeriod

    client = bigquery.Client(project=project)

    loads = [
        (
            "teams",
            transform_teams(league, season, snapshot_date, ingested_at),
            ["season", "snapshot_date", "team_id"],
        ),
        (
            "matchup_categories",
            transform_matchup_categories(league, season, current_matchup_period, ingested_at),
            ["season", "matchup_period", "team_id", "category"],
        ),
        (
            "rosters",
            transform_rosters(league, season, snapshot_date, ingested_at),
            ["season", "snapshot_date", "team_id", "player_id"],
        ),
        (
            "player_stats",
            transform_player_stats(league, season, snapshot_date, ingested_at),
            ["season", "snapshot_date", "player_id", "stat_window"],
        ),
        (
            "transactions",
            transform_transactions(league, season, activity_size, ingested_at),
            ["txn_id"],
        ),
    ]

    for table, df, key_columns in loads:
        merge_load(client, project, dataset, table, df, key_columns)

    print("Ingest complete.")


if __name__ == "__main__":
    main()
