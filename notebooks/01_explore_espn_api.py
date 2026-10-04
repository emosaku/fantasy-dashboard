"""Step 2: local data access.

One-off exploration script, not part of the ingest job -- proves `espn-api` can pull
every data source the six features need, and inspects real field names with `vars()`
rather than trusting the library's docs (they shift between versions).
"""

import os

from dotenv import load_dotenv
from espn_api.basketball import League

load_dotenv()


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> None:
    league = League(
        league_id=int(os.environ["LEAGUE_ID"]),
        year=int(os.environ["SEASON"]),
        espn_s2=os.environ["ESPN_S2"],
        swid=os.environ["SWID"],
    )

    section("Teams")
    for team in league.teams:
        print(team.team_id, team.team_name, team.wins, team.losses)

    section("Team object fields (vars)")
    print(vars(league.teams[0]))

    section("Box scores, matchup_period=1")
    box_scores = league.box_scores(matchup_period=1)
    print(f"{len(box_scores)} matchups")
    print(vars(box_scores[0]))

    section("Recent activity (adds/drops/trades)")
    activity = league.recent_activity(size=10)
    print(f"{len(activity)} recent actions")
    if activity:
        print(vars(activity[0]))

    section("Roster + player stats, team 0")
    roster = league.teams[0].roster
    print(f"{len(roster)} players")
    if roster:
        print(vars(roster[0]))


if __name__ == "__main__":
    main()
