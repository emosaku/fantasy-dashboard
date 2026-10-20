"""Fill in birth dates and ESPN ids on `nba_players` from Wikidata and ESPN's player
list (ingest/projections/people.py), and report how much of the league got matched.
Only players with NBA games are matched: BallDontLie's list also holds other leagues'.

Coverage is weighted by minutes played in the last three loaded seasons, since an
unmatched starter matters far more than an unmatched two-way player. Then the matched
ESPN ids are checked against ESPN's own preseason player list
(`espn_projection_snapshot`): the names should agree. Uses your gcloud login.

    python scripts/match_players.py --project league-lab-whop
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
from google.cloud import bigquery

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ingest.bigquery_load import replace_rows  # noqa: E402
from ingest.projections.people import (  # noqa: E402
    fetch_espn_players,
    fetch_wikidata,
    match,
    normalize,
)

ESPN_SEASONS = (2026, 2027)  # ESPN's player lists to take ids from: last season and this


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--project", required=True)
    parser.add_argument("--dataset", default="league_lab")
    args = parser.parse_args()
    bq = bigquery.Client(project=args.project)
    table = f"{args.project}.{args.dataset}"

    players = bq.query(f"SELECT * FROM `{table}.nba_players`").to_dataframe()
    nba = bq.query(f"SELECT DISTINCT player_id FROM `{table}.nba_player_games`").to_dataframe()[
        "player_id"
    ]
    espn = pd.concat([fetch_espn_players(s) for s in ESPN_SEASONS]).drop_duplicates(
        "espn_player_id", keep="last"
    )
    matched = match(players.loc[players["player_id"].isin(nba)], fetch_wikidata(), espn)
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
    total = recent["minutes"].sum()
    print(f"{len(nba)} players with NBA games; {len(matched)} matched")
    for column, label in (("birth_date", "birth date"), ("espn_player_id", "ESPN id")):
        has = recent[column].notna()
        share = recent.loc[has, "minutes"].sum() / total
        print(f"{label}: {share:.1%} of the last 3 seasons' minutes")
        missing = recent.loc[~has].nlargest(10, "minutes")
        pairs = zip(missing["player_name"], missing["minutes"], strict=True)
        print("  biggest missing:", ", ".join(f"{n} ({m:.0f} min)" for n, m in pairs))

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
