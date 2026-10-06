"""Apply League Lab's SQL to a project: tables, then views, then the precomputed
m_* tables, in dependency order. Safe to re-run: tables are CREATE IF NOT EXISTS,
views CREATE OR REPLACE, precomputed tables rebuilt from their views.

    python scripts/apply_sql.py --project league-lab-emk --dataset league_lab

SQL files use {project} and {dataset} placeholders, so the same files serve any
project. Files run in name order within sql/ddl/ and sql/views/.
"""

import argparse
import sys
from pathlib import Path

from google.cloud import bigquery

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ingest.materialize import MATERIALIZED_VIEWS, rebuild_statement  # noqa: E402


def render(path: Path, project: str, dataset: str) -> str:
    return path.read_text().replace("{project}", project).replace("{dataset}", dataset)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--project", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--location", default="us-west1")
    args = parser.parse_args()

    client = bigquery.Client(project=args.project)
    dataset = bigquery.Dataset(f"{args.project}.{args.dataset}")
    dataset.location = args.location
    client.create_dataset(dataset, exists_ok=True)

    for folder in ("ddl", "views"):
        for path in sorted((ROOT / "sql" / folder).glob("*.sql")):
            client.query(render(path, args.project, args.dataset)).result()
            print(f"applied {folder}/{path.name}")
    for view in MATERIALIZED_VIEWS:
        client.query(rebuild_statement(args.project, args.dataset, view)).result()
        print(f"rebuilt m_{view.removeprefix('v_')}")


if __name__ == "__main__":
    main()
