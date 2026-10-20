"""Backtest our projection model on real seasons (docs/whopDocs/projections.md).

Reads every game line from `nba_player_games` and birth dates from `nba_players`,
fits the model on earlier seasons only for each test season, and prints each measure
for the model and for "repeat last season" (the baseline it must clearly beat). With
--tune it first searches ingest/projections/backtest.py's grid and backtests the best
settings. Uses your gcloud login; reads only.

    python scripts/backtest_projections.py --project league-lab-whop --seasons 2024 2025 2026
    python scripts/backtest_projections.py --project league-lab-whop --seasons 2024 2025 2026 \\
        --tune
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--project", required=True)
    parser.add_argument("--dataset", default="league_lab")
    parser.add_argument("--seasons", type=int, nargs="+", required=True)
    parser.add_argument("--tune", action="store_true")
    args = parser.parse_args()

    seasons, players = load(bigquery.Client(project=args.project), args.project, args.dataset)
    print(f"{len(seasons)} player-seasons, {seasons['season'].nunique()} seasons, "
          f"{players['birth_date'].notna().sum()} birth dates")  # fmt: skip
    params = DEFAULT
    if args.tune:
        params, table = tune(seasons, args.seasons, players)
        print(table.head(10).to_string(index=False))
        print(f"best: {params}")
    scored = backtest(seasons, args.seasons, players, params)
    pd.set_option("display.width", 200)
    print(scored[SHOWN].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
