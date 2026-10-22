"""Write our preseason projections for a season to `projections` (ingest/projections/
run.py), from every loaded season before it. The ingest job reads the newest run and
writes it into each league's "projected" window on its next refresh. Re-running
replaces that season's preseason rows for the current model version. Uses your gcloud
login.

    python scripts/make_projections.py --project league-lab-whop --season 2027
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

from google.cloud import bigquery

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ingest.projections.run import MODEL_VERSION, latest, make_preseason  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--project", required=True)
    parser.add_argument("--dataset", default="league_lab")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()

    client = bigquery.Client(project=args.project)
    made = make_preseason(client, args.project, args.dataset, args.season, dt.datetime.now(dt.UTC))
    linked = latest(client, args.project, args.dataset, args.season)
    print(f"season {args.season}, model {MODEL_VERSION}: {made} players projected, "
          f"{len(linked)} linked to ESPN ids")  # fmt: skip


if __name__ == "__main__":
    main()
