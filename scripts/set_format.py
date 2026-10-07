"""Change a league's locked format -- the site owner's fix for a league registered in
the wrong format, or one whose ESPN scoring type changed mid-season (its pages then
show the mismatch banner and its data stops refreshing).

In order:
  1. delete the league's rows from both formats' own tables (category results and
     categories; points scores, values, fantasy points and schedule), so nothing
     from the old format is left;
  2. lock the new format for the league's season in Firestore, clear the mismatch
     flag and the "scores final through" marker, and mark the league pending;
  3. with --reload, run the ingest job for that league now (otherwise the next
     morning's run reloads it).

Prints what it would do unless --yes is given. Uses your gcloud login.

    python scripts/set_format.py --project league-lab-emk --league 12345 --format points
    python scripts/set_format.py --project league-lab-emk --league 12345 --format points \\
        --reload --yes
"""

import argparse
import datetime as dt
import subprocess

from google.cloud import bigquery, firestore

FORMAT_TABLES = ["league_categories", "matchup_categories", "league_scoring", "player_points",
                 "matchup_scores", "pro_schedule"]  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--project", required=True)
    parser.add_argument("--dataset", default="league_lab")
    parser.add_argument("--region", default="us-west1")
    parser.add_argument("--job", default="league-ingest")
    parser.add_argument("--league", type=int, required=True)
    parser.add_argument("--format", choices=["categories", "points"], required=True)
    parser.add_argument("--reload", action="store_true", help="run the ingest job now")
    parser.add_argument("--yes", action="store_true", help="do it (default: dry run)")
    args = parser.parse_args()

    db = firestore.Client(project=args.project)
    ref = db.collection("leagues").document(str(args.league))
    doc = ref.get().to_dict()
    if doc is None:
        raise SystemExit(f"No league {args.league} in the registry.")
    season = int(doc.get("season"))
    print(f"League {args.league} ({doc.get('league_name')}): {doc.get('format') or 'categories'}"
          f" -> {args.format}, locked for the {season} season.")  # fmt: skip

    script = ";\n".join(
        f"DELETE FROM `{args.project}.{args.dataset}.{t}` WHERE league_id = {args.league}"
        for t in FORMAT_TABLES
    )
    fields = {
        "format": args.format,
        "format_season": season,
        "format_locked_at": dt.datetime.now(dt.UTC),
        "format_confirmed_by": "site owner",
        "format_mismatch": None,
        "scores_final_through": 0,
        "status": "pending",
    }
    reload_cmd = ["gcloud", "run", "jobs", "execute", args.job, "--region", args.region,
                  "--project", args.project, f"--update-env-vars=LEAGUE_IDS={args.league}",
                  "--tasks=1"]  # fmt: skip
    print(script)
    print("Firestore:", {k: v for k, v in fields.items() if k != "format_locked_at"})
    if args.reload:
        print("$", " ".join(reload_cmd))
    if not args.yes:
        print("Dry run. Add --yes to do it.")
        return
    bigquery.Client(project=args.project).query(script).result()
    ref.set(fields, merge=True)
    if args.reload:
        subprocess.run(reload_cmd, check=True)
    print("Done.")


if __name__ == "__main__":
    main()
