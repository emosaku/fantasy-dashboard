"""Save ESPN's preseason projections once, as a private benchmark for our own model.

ESPN's API serves only its current projections, which change once games start, so the
preseason version has to be captured before the season begins. The backtest
(docs/whopDocs/projections.md) scores our model and this snapshot against the actual
season. Benchmark only: no page reads this table, and it is never shown to users.

Saves every player in ESPN's league-independent pool that has a projection for the
season: ESPN's ranks and ADP for context, the projected per-game line and games, and
the raw record, into `espn_projection_snapshot` (created if missing; each run appends
rows under its own snapshot_at). Uses your gcloud login.

    python scripts/snapshot_espn_projections.py --project league-lab-whop --season 2027
"""

import argparse
import datetime as dt
import json

import pandas as pd
from espn_api.basketball.constant import POSITION_MAP, PRO_TEAM_MAP, STATS_MAP
from google.cloud import bigquery
from ingest.espn_client import DEFAULTS_URL, _get

GAMES_PLAYED_STAT = "42"
TABLE = "espn_projection_snapshot"
SCHEMA = [
    bigquery.SchemaField("snapshot_at", "TIMESTAMP", "REQUIRED"),
    bigquery.SchemaField("season", "INT64", "REQUIRED"),
    bigquery.SchemaField("player_id", "INT64", "REQUIRED"),
    bigquery.SchemaField("player_name", "STRING"),
    bigquery.SchemaField("pro_team", "STRING"),
    bigquery.SchemaField("position", "STRING"),
    bigquery.SchemaField("rank_standard", "INT64"),
    bigquery.SchemaField("rank_roto", "INT64"),
    bigquery.SchemaField("adp", "FLOAT64"),
    bigquery.SchemaField("projected_games", "FLOAT64"),
    bigquery.SchemaField("projected_per_game", "STRING"),  # JSON text: {"PTS": 27.1, ...}
    bigquery.SchemaField("raw", "STRING"),  # JSON text: ESPN's whole record, for anything missed
]


def fetch_pool(season: int, size: int) -> list[dict]:
    filters = {
        "players": {
            "limit": size,
            "sortDraftRanks": {"sortPriority": 100, "sortAsc": True, "value": "STANDARD"},
            "filterStatsForSourceIds": {"value": [1]},
            "filterStatsForSplitTypeIds": {"value": [0]},
        }
    }
    headers = {"x-fantasy-filter": json.dumps(filters)}
    data = _get(DEFAULTS_URL.format(season=season), {"view": "kona_player_info"}, headers, None)
    return [entry["player"] for entry in data.get("players", [])]


def projection(record: dict, season: int) -> dict | None:
    for stat in record.get("stats") or []:
        if (stat.get("seasonId"), stat.get("statSourceId"), stat.get("statSplitTypeId")) == (
            season, 1, 0,
        ):  # fmt: skip
            return stat
    return None


def rows(records: list[dict], season: int, now: dt.datetime) -> pd.DataFrame:
    out = []
    for r in records:
        proj = projection(r, season)
        if not proj:
            continue
        line = {STATS_MAP[k]: float(v) for k, v in (proj.get("averageStats") or {}).items()
                if STATS_MAP.get(k)}  # fmt: skip
        ranks = r.get("draftRanksByRankType") or {}
        games = (proj.get("stats") or {}).get(GAMES_PLAYED_STAT)
        out.append(
            {
                "snapshot_at": now,
                "season": season,
                "player_id": int(r["id"]),
                "player_name": r.get("fullName"),
                "pro_team": PRO_TEAM_MAP.get(r.get("proTeamId")),
                "position": POSITION_MAP.get((r.get("defaultPositionId") or 0) - 1),
                "rank_standard": (ranks.get("STANDARD") or {}).get("rank"),
                "rank_roto": (ranks.get("ROTO") or {}).get("rank"),
                "adp": (r.get("ownership") or {}).get("averageDraftPosition"),
                "projected_games": float(games) if games is not None else None,
                "projected_per_game": json.dumps(line),
                "raw": json.dumps(r),
            }
        )
    return pd.DataFrame(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--project", required=True)
    parser.add_argument("--dataset", default="league_lab")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--size", type=int, default=1500)
    args = parser.parse_args()

    now = dt.datetime.now(dt.UTC)
    df = rows(fetch_pool(args.season, args.size), args.season, now)
    client = bigquery.Client(project=args.project)
    job = client.load_table_from_dataframe(
        df,
        f"{args.project}.{args.dataset}.{TABLE}",
        job_config=bigquery.LoadJobConfig(schema=SCHEMA, write_disposition="WRITE_APPEND"),
    )
    job.result()
    print(f"saved {len(df)} projections for season {args.season} at {now:%Y-%m-%d %H:%M} UTC")


if __name__ == "__main__":
    main()
