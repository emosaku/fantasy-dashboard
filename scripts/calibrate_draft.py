"""Refit the Draft Tool's opponent model on the real drafts League Lab has loaded.

For every registered league whose draft ESPN has published (the draft_picks table),
rebuilds its draft pool, replays the draft and fits how far managers stray from the
board (app/draft/calibrate.py). Prints the fitted settings and how well they predict
who's still there 10 picks later; copy them into OpponentModel's defaults in
app/draft/simulate.py when they change. Reads only. Uses your gcloud login.

    python scripts/calibrate_draft.py --project league-lab-emk
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
from google.cloud import bigquery, firestore

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "app")]
from draft import calibrate  # noqa: E402
from draft import pool as dpool  # noqa: E402
from draft.simulate import OpponentModel  # noqa: E402
from draft.state import Order  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--project", required=True)
    parser.add_argument("--dataset", default="league_lab")
    args = parser.parse_args()
    bq = bigquery.Client(project=args.project)
    db = firestore.Client(project=args.project)

    def table(name: str, league_id: int) -> pd.DataFrame:
        sql = f"SELECT * FROM `{args.project}.{args.dataset}.{name}` WHERE league_id = {league_id}"
        return bq.query(sql).to_dataframe(create_bqstorage_client=False)

    drafts = []
    for snap in db.collection("leagues").stream():
        doc = snap.to_dict() or {}
        league_id, settings = int(snap.id), doc.get("draft") or {}
        picks = table("draft_picks", league_id)
        if picks.empty or not settings.get("pick_order"):
            continue
        rank = "rank" if doc.get("format") == "points" else "rank_roto"
        slots = doc.get("lineup_slots") or {"UT": 1}
        pool = dpool.build(table("draft_pool", league_id), slots, rank)
        order = Order(tuple(settings["pick_order"]), int(settings["rounds"]))
        pairs = list(zip(picks.sort_values("overall")["team_id"],
                         picks.sort_values("overall")["player_id"], strict=True))  # fmt: skip
        drafts.append((order, pairs, pool, calibrate.BoardOnly(len(pool.frame))))
        print(f"{doc.get('league_name')}: {len(order.teams)} teams x {order.rounds} rounds")
    if not drafts:
        raise SystemExit("No published drafts yet.")
    model, grid = calibrate.fit(drafts)
    print(grid.head(5).to_string())
    print("current:", OpponentModel())
    print("fitted: ", model)
    checks = pd.concat(
        calibrate.availability_check(o, p, pool, fmt, model, every=5) for o, p, pool, fmt in drafts
    )
    print(calibrate.reliability(checks).round(3).to_string())
    print(f"Brier score {calibrate.brier(checks):.3f}")


if __name__ == "__main__":
    main()
