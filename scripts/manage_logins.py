"""Create or reset the dashboard's manager logins.

    python scripts/manage_logins.py                    # a login for every manager without one
    python scripts/manage_logins.py --reset eni.mosaku # a new password for one manager

Reads the league's managers from BigQuery (latest teams snapshot), gives each a
username (first.last) and a random password, and writes:

  * .streamlit/secrets.toml -- salted scrypt hashes only, never passwords. Git-ignored.
    Streamlit reads it as st.secrets; in Step 7 it's mounted from Secret Manager.
  * manager-logins.csv -- the plain passwords created or reset in THIS run, for the
    commissioner to hand out. Git-ignored. Delete it once they're sent.

Existing logins keep their passwords (re-running only adds new managers), and a
manager no longer in the league is removed. --admin marks an account that can view
any team in the Trade Analyzer; the commissioner (eni.mosaku) is one by default.
"""

import argparse
import csv
import os
import sys
import tomllib
from pathlib import Path

from google.cloud import bigquery

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from auth import hash_password, new_password, username_for  # noqa: E402

SECRETS = ROOT / ".streamlit" / "secrets.toml"
LOGINS_CSV = ROOT / "manager-logins.csv"
PROJECT = os.environ.get("GCP_PROJECT_ID", "fantasy-dash-emk")
DEFAULT_ADMINS = {"eni.mosaku"}


def managers() -> list[dict]:
    """[{name, team_id, team_name}] from the latest teams snapshot, one per manager
    (a co-managed team's owner field lists several, comma-separated)."""
    table = f"`{PROJECT}.fantasy.teams`"
    rows = (
        bigquery.Client(project=PROJECT)
        .query(f"""
        SELECT team_id, TRIM(team_name) AS team_name, owner
        FROM {table}
        WHERE season = (SELECT MAX(season) FROM {table})
        QUALIFY ROW_NUMBER() OVER (PARTITION BY team_id ORDER BY snapshot_date DESC) = 1
        ORDER BY team_id
    """)
        .result()
    )
    out = []
    for row in rows:
        for name in (row.owner or "").split(","):
            if name.strip():
                out.append(
                    {"name": name.strip(), "team_id": row.team_id, "team_name": row.team_name}
                )
    return out


def load_users() -> dict:
    if not SECRETS.exists():
        return {}
    data = tomllib.loads(SECRETS.read_text())
    if set(data) - {"auth"}:
        sys.exit(f"{SECRETS} holds more than logins; edit it by hand instead.")
    return data.get("auth", {}).get("users", {})


def toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_users(users: dict) -> None:
    lines = [
        "# Dashboard manager logins -- written by scripts/manage_logins.py.",
        "# Salted scrypt hashes only; the passwords themselves are never stored.",
        "# Git-ignored. Don't edit by hand: re-run the script (--reset to change one).",
        "",
    ]
    for username in sorted(users):
        user = users[username]
        lines += [
            f"[auth.users.{toml_string(username)}]",
            f"name = {toml_string(user['name'])}",
            f"team_id = {int(user['team_id'])}",
            f"admin = {'true' if user.get('admin') else 'false'}",
            f"salt = {toml_string(user['salt'])}",
            f"hash = {toml_string(user['hash'])}",
            "",
        ]
    SECRETS.parent.mkdir(exist_ok=True)
    SECRETS.write_text("\n".join(lines))
    SECRETS.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--reset", nargs="*", default=[], help="usernames to give new passwords")
    parser.add_argument("--admin", nargs="*", default=[], help="usernames that can view any team")
    args = parser.parse_args()

    existing = load_users()
    admins = DEFAULT_ADMINS | set(args.admin)
    users, issued, taken = {}, [], set()
    for manager in managers():
        username = username_for(manager["name"])
        if username in taken:  # two managers with the same name
            username = f"{username}.{manager['team_id']}"
        taken.add(username)

        old = existing.get(username)
        if old and username not in args.reset:
            salt, digest = old["salt"], old["hash"]
        else:
            password = new_password()
            salt, digest = hash_password(password)
            issued.append({**manager, "username": username, "password": password})
        users[username] = {
            "name": manager["name"],
            "team_id": manager["team_id"],
            "admin": username in admins,
            "salt": salt,
            "hash": digest,
        }

    for gone in sorted(set(existing) - set(users)):
        print(f"Removed {gone}: no longer a manager in the league.")
    for unknown in sorted(set(args.reset) - set(users)):
        print(f"No manager with username {unknown!r}; nothing reset.")
    write_users(users)
    print(f"{len(users)} logins in {SECRETS.relative_to(ROOT)}.")

    if issued:
        with LOGINS_CSV.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Manager", "Team", "Username", "Password"])
            for row in issued:
                writer.writerow([row["name"], row["team_name"], row["username"], row["password"]])
        LOGINS_CSV.chmod(0o600)
        print(
            f"{len(issued)} new password(s) in {LOGINS_CSV.name}. Send each manager theirs, "
            "then delete the file."
        )
    else:
        print("No new passwords issued; existing logins unchanged.")


if __name__ == "__main__":
    main()
