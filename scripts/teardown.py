"""Shut League Lab down in one command -- e.g. the day a cease-and-desist arrives.

In order:
  1. pause the daily ingest schedule (no more requests to ESPN);
  2. put up the shutdown page (SHUTDOWN=1 on the dashboard service);
  3. delete every stored ESPN credential (Secret Manager secrets named league-*);
  4. delete every league's data: the BigQuery dataset, and the Firestore leagues,
     members and users collections.

Prints what it would do unless --yes is given. Uses your gcloud login. Doesn't delete
the project, the code, the kill switch or billing: to remove everything, delete the
project afterwards (`gcloud projects delete league-lab-emk`).

    python scripts/teardown.py --project league-lab-emk           # dry run
    python scripts/teardown.py --project league-lab-emk --yes     # do it
"""

import argparse
import subprocess

from google.cloud import bigquery, firestore, secretmanager

COLLECTIONS = ["members", "leagues", "users"]


def run(cmd: list[str], really: bool) -> None:
    print("$", " ".join(cmd))
    if really:
        subprocess.run(cmd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", default="us-west1")
    parser.add_argument("--dataset", default="league_lab")
    parser.add_argument("--service", default="league-lab")
    parser.add_argument("--schedule", default="league-ingest-daily")
    parser.add_argument("--yes", action="store_true", help="actually do it")
    args = parser.parse_args()
    really = args.yes
    print("TEARDOWN" if really else "DRY RUN (add --yes to do it)", "--", args.project)

    print("\n1. Pause the daily ingest")
    run(["gcloud", "scheduler", "jobs", "pause", args.schedule,
         f"--location={args.region}", f"--project={args.project}"], really)  # fmt: skip

    print("\n2. Shutdown page")
    run(["gcloud", "run", "services", "update", args.service, "--update-env-vars=SHUTDOWN=1",
         f"--region={args.region}", f"--project={args.project}", "--quiet"], really)  # fmt: skip

    print("\n3. Stored ESPN credentials")
    secrets = secretmanager.SecretManagerServiceClient()
    for secret in secrets.list_secrets(parent=f"projects/{args.project}"):
        if secret.name.rsplit("/", 1)[-1].startswith("league-"):
            print("delete secret", secret.name)
            if really:
                secrets.delete_secret(name=secret.name)

    print("\n4. League data")
    print(f"delete BigQuery dataset {args.project}.{args.dataset} (all tables)")
    if really:
        bigquery.Client(project=args.project).delete_dataset(
            f"{args.project}.{args.dataset}", delete_contents=True, not_found_ok=True
        )
    db = firestore.Client(project=args.project)
    for name in COLLECTIONS:
        docs = list(db.collection(name).stream())
        print(f"delete Firestore {name}: {len(docs)} documents")
        if really:
            for doc in docs:
                doc.reference.delete()

    print("\nDone." if really else "\nNothing changed.")


if __name__ == "__main__":
    main()
