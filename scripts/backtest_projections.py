"""Backtest our projection model on real seasons (docs/whopDocs/projections.md).

Reads every game line from `nba_player_games` and birth dates from `nba_players`,
fits the model on earlier seasons only for each test season, and prints each measure
for the model and for "repeat last season" (the baseline it must clearly beat). With
--tune it first searches ingest/projections/backtest.py's grid and backtests the best
settings. With --espn, ESPN's projections are scored alongside, on the same players:
each record in `espn_projection_snapshot` also carries ESPN's projection for earlier
seasons (whether that's its preseason version or a later revision isn't known, so treat
it as a rough benchmark; the 2026-27 snapshot is the clean one). Uses your gcloud
login; reads only.

    python scripts/backtest_projections.py --project league-lab-whop --seasons 2024 2025 2026
    python scripts/backtest_projections.py --project league-lab-whop --seasons 2024 2025 2026 \\
        --tune --espn
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
from espn_api.basketball.constant import STATS_MAP
from google.cloud import bigquery

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ingest.projections.backtest import backtest, tune  # noqa: E402
from ingest.projections.games import COLUMNS, STATS, from_columns, season_lines  # noqa: E402
from ingest.projections.model import DEFAULT  # noqa: E402

SHOWN = ["season", "method", "players", "mae_fpg", "mae_fp", "rank_corr", "mae_MIN",
         "mae_PTS", "mae_REB", "mae_AST"]  # fmt: skip


def load(client: bigquery.Client, project: str, dataset: str):
    stats = ", ".join(COLUMNS[s] for s in STATS)
    games = client.query(
        f"SELECT player_id, season, game_date, {stats} FROM `{project}.{dataset}.nba_player_games`"
    ).to_dataframe()
    players = client.query(
        f"SELECT player_id, birth_date FROM `{project}.{dataset}.nba_players`"
    ).to_dataframe()
    return season_lines(from_columns(games)), players


def espn_projections(client: bigquery.Client, project: str, dataset: str) -> dict:
    """{season: per-game projections keyed by BallDontLie id} from the snapshot's raw
    ESPN records, for every season they carry a projection for."""
    snap = client.query(
        f"SELECT s.raw, p.player_id FROM `{project}.{dataset}.espn_projection_snapshot` s "
        f"JOIN `{project}.{dataset}.nba_players` p ON p.espn_player_id = s.player_id"
    ).to_dataframe()
    by_season: dict = {}
    for raw, player_id in zip(snap["raw"], snap["player_id"], strict=True):
        for stat in json.loads(raw).get("stats") or []:
            if stat.get("statSourceId") != 1 or stat.get("statSplitTypeId") != 0:
                continue
            avg = {STATS_MAP.get(k): float(v) for k, v in (stat.get("averageStats") or {}).items()}
            games = (stat.get("stats") or {}).get("42")
            row = {"player_id": int(player_id), "GP": float(games) if games else None}
            row |= {s: avg.get(s, 0.0) for s in STATS}
            by_season.setdefault(int(stat["seasonId"]), []).append(row)
    return {season: pd.DataFrame(rows) for season, rows in by_season.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--project", required=True)
    parser.add_argument("--dataset", default="league_lab")
    parser.add_argument("--seasons", type=int, nargs="+", required=True)
    parser.add_argument("--tune", action="store_true")
    parser.add_argument("--tune-on", type=int, nargs="+", help="tune on other seasons")
    parser.add_argument("--espn", action="store_true", help="score ESPN's projections too")
    args = parser.parse_args()

    client = bigquery.Client(project=args.project)
    seasons, players = load(client, args.project, args.dataset)
    print(f"{len(seasons)} player-seasons, {seasons['season'].nunique()} seasons, "
          f"{players['birth_date'].notna().sum()} birth dates")  # fmt: skip
    params = DEFAULT
    if args.tune:
        params, table = tune(seasons, args.tune_on or args.seasons, players)
        print(table.head(10).to_string(index=False))
        print(f"best: {params}")
    others = {"espn": espn_projections(client, args.project, args.dataset)} if args.espn else None
    scored = backtest(seasons, args.seasons, players, params, others)
    pd.set_option("display.width", 200)
    print(scored[SHOWN].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
