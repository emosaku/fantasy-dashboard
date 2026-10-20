"""Fill in birth dates and ESPN ids on `nba_players` from Wikidata
(ingest/projections/people.py), and report how much of the league got matched.

Coverage is weighted by minutes played in the last three loaded seasons, since an
unmatched starter matters far more than an unmatched two-way player. Then the matched
ESPN ids are checked against ESPN's own preseason player list
(`espn_projection_snapshot`): the names should agree. Uses your gcloud login.

    python scripts/match_players.py --project league-lab-whop
"""

import argparse
import sys
from pathlib import Path

from google.cloud import bigquery

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ingest.bigquery_load import replace_rows  # noqa: E402
from ingest.projections.people import fetch_wikidata, match, normalize  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--project", required=True)
    parser.add_argument("--dataset", default="league_lab")
    args = parser.parse_args()
    bq = bigquery.Client(project=args.project)
    table = f"{args.project}.{args.dataset}"

    players = bq.query(f"SELECT * FROM `{table}.nba_players`").to_dataframe()
    matched = match(players, fetch_wikidata())
    players = players.drop(columns=["birth_date", "espn_player_id"]).merge(
        matched, on="player_id", how="left"
    )
    replace_rows(bq, args.project, args.dataset, "nba_players", players, "TRUE")

    minutes = bq.query(
        f"SELECT player_id, SUM(min) AS minutes FROM `{table}.nba_player_games` "
        f"WHERE season > (SELECT MAX(season) - 3 FROM `{table}.nba_player_games`) "
        "GROUP BY player_id"
    ).to_dataframe()
    recent = minutes.merge(players, on="player_id", how="left")
    share = recent.loc[recent["espn_player_id"].notna(), "minutes"].sum() / recent["minutes"].sum()
    print(f"matched {matched['player_id'].nunique()} of {len(players)} players; "
          f"{share:.1%} of the last 3 seasons' minutes")  # fmt: skip
    missing = recent.loc[recent["espn_player_id"].isna()].nlargest(15, "minutes")
    pairs = zip(missing["player_name"], missing["minutes"], strict=True)
    print("biggest unmatched:", ", ".join(f"{n} ({m:.0f} min)" for n, m in pairs))

    espn = bq.query(
        f"SELECT DISTINCT player_id AS espn_player_id, player_name AS espn_name "
        f"FROM `{table}.espn_projection_snapshot`"
    ).to_dataframe()
    check = espn.merge(players, on="espn_player_id", how="left")
    found = check["player_name"].notna()
    agree = check.loc[found, "espn_name"].map(normalize) == check.loc[found, "player_name"].map(
        normalize
    )
    print(f"ESPN's preseason list: {found.sum()} of {len(espn)} found, "
          f"{agree.sum()} with the same name")  # fmt: skip
    print("not found:", ", ".join(check.loc[~found, "espn_name"].head(15)))


if __name__ == "__main__":
    main()
