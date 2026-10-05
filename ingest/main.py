"""Entry point for the espn-ingest Cloud Run Job (Step 4).

Builds the espn_api League object from LEAGUE_ID/SEASON/ESPN_S2/SWID (injected as env
vars via Cloud Run's --set-secrets, not read from Secret Manager directly), pulls the
five data sources described in docs/proposal.md (Step 3) plus the league's status
(current week, season length) and its top free agents -- both added in Step 6 -- and
MERGEs each into its BigQuery
target table via a staging table for idempotency.
"""

import os
from datetime import UTC, datetime

from google.cloud import bigquery

from ingest.bigquery_load import merge_load
from ingest.espn_client import build_league, fetch_player_info
from ingest.transform import (
    fetch_activity,
    transform_free_agents,
    transform_league_status,
    transform_matchup_categories,
    transform_player_details,
    transform_player_seasons,
    transform_player_stats,
    transform_rosters,
    transform_teams,
    transform_transactions,
)


def main() -> None:
    season = int(os.environ["SEASON"])
    project = os.environ.get("GCP_PROJECT_ID", "fantasy-dash-emk")
    dataset = os.environ.get("BIGQUERY_DATASET", "fantasy")
    free_agent_count = int(os.environ.get("FREE_AGENT_COUNT", "100"))
    history_seasons = int(os.environ.get("HISTORY_SEASONS", "3"))

    league = build_league()
    ingested_at = datetime.now(UTC)
    snapshot_date = ingested_at.date()
    current_matchup_period = league.currentMatchupPeriod
    free_agents = league.free_agents(size=free_agent_count)

    # Health details and games-played history for the whole pool (rostered players
    # + free agents), straight from ESPN's player records.
    pool_ids = sorted(
        {p.playerId for team in league.teams for p in team.roster}
        | {p.playerId for p in free_agents}
    )
    current_records = fetch_player_info(season, pool_ids)
    history = {s: fetch_player_info(s, pool_ids) for s in range(season - history_seasons, season)}

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
            transform_player_stats(league, season, snapshot_date, ingested_at, free_agents),
            ["season", "snapshot_date", "player_id", "stat_window"],
        ),
        (
            "transactions",
            transform_transactions(fetch_activity(league), season, ingested_at, league.player_map),
            ["txn_id"],
        ),
        (
            "free_agents",
            transform_free_agents(free_agents, season, snapshot_date, ingested_at),
            ["season", "snapshot_date", "player_id"],
        ),
        (
            "player_details",
            transform_player_details(current_records, season, snapshot_date, ingested_at),
            ["season", "snapshot_date", "player_id"],
        ),
        (
            "player_seasons",
            transform_player_seasons(history, season, ingested_at),
            ["season", "player_id", "history_season"],
        ),
        (
            "league_status",
            transform_league_status(league, season, snapshot_date, ingested_at),
            ["season", "snapshot_date"],
        ),
    ]

    # Tables keyed by snapshot_date hold one complete picture per day: this run
    # replaces the day's rows rather than only adding to them.
    today = {"season": season, "snapshot_date": snapshot_date}
    for table, df, key_columns in loads:
        scope = today if "snapshot_date" in key_columns else None
        merge_load(client, project, dataset, table, df, key_columns, scope)

    print("Ingest complete.")


if __name__ == "__main__":
    main()
