"""Load BallDontLie game stats and players into BigQuery (docs/whopDocs/projections.md).

For each season given, every player's line in every regular-season game replaces that
season's rows in `nba_player_games` (re-running a season gives the same rows). With
--players, the player list replaces `nba_players`, keeping any birth dates and ESPN ids
already matched. A season is about 330 requests, ~6 minutes at ALL-STAR's 60 a minute.
Seasons are League Lab's (by end year: 2026 = 2025-26). Uses your gcloud login; the
API key comes from Secret Manager.

    python scripts/backfill_nba.py --project league-lab-whop --seasons 2017 2018 2019
    python scripts/backfill_nba.py --project league-lab-whop --players
    python scripts/backfill_nba.py --project league-lab-whop --seasons 2025 \\
        --start 2025-01-01 --end 2025-01-03   # a date range, for a quick check
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

from google.cloud import bigquery

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ingest.bigquery_load import replace_rows  # noqa: E402
from ingest.projections.source import Client, api_key, game_rows, player_rows  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--project", required=True)
    parser.add_argument("--dataset", default="league_lab")
    parser.add_argument("--seasons", type=int, nargs="*", default=[])
    parser.add_argument("--start", type=dt.date.fromisoformat)
    parser.add_argument("--end", type=dt.date.fromisoformat)
    parser.add_argument("--players", action="store_true")
    args = parser.parse_args()

    bdl = Client(api_key(args.project))
    bq = bigquery.Client(project=args.project)
    for season in args.seasons:
        started = dt.datetime.now(dt.UTC)
        rows = game_rows(bdl.game_stats(season, args.start, args.end), started)
        scope = f"season = {season}"
        if args.start or args.end:
            first, last = args.start or "1900-01-01", args.end or "2100-01-01"
            scope += f" AND game_date BETWEEN '{first}' AND '{last}'"
        replace_rows(bq, args.project, args.dataset, "nba_player_games", rows, scope)
        played = rows.loc[rows["min"] > 0] if not rows.empty else rows
        took = (dt.datetime.now(dt.UTC) - started).total_seconds() / 60
        print(f"season {season}: {len(rows)} rows, {rows['game_id'].nunique() if len(rows) else 0} "
              f"games, {played['player_id'].nunique() if len(rows) else 0} players, "
              f"{took:.1f} min", flush=True)  # fmt: skip
    if args.players:
        now = dt.datetime.now(dt.UTC)
        rows = player_rows(bdl.players(), now)
        table = f"{args.project}.{args.dataset}.nba_players"
        kept = bq.query(
            f"SELECT player_id, birth_date, espn_player_id FROM `{table}` "
            "WHERE birth_date IS NOT NULL OR espn_player_id IS NOT NULL"
        ).to_dataframe()
        if not kept.empty:
            rows = rows.drop(columns=["birth_date", "espn_player_id"]).merge(
                kept, on="player_id", how="left"
            )
        replace_rows(bq, args.project, args.dataset, "nba_players", rows, "TRUE")
        print(f"players: {len(rows)}")


if __name__ == "__main__":
    main()
