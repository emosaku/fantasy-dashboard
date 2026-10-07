# League Lab for points leagues: pages and metrics

*October 7, 2026. Branch `PointsLeague`.*

League Lab runs head-to-head **points** leagues as well as categories leagues. A
league's format comes from its ESPN settings, is confirmed when it's registered, and
is locked for the season. Every page has the same name and address in both formats;
in a points league each one measures fantasy points instead of categories.

## The format lock

- **At registration** the preview says which format ESPN reports ("This league plays
  head-to-head points. League Lab will run its points tools for the 2026-27 season,
  and the format can't change until next season") and lists the point values. The
  commissioner confirms it with the registration checkbox.
- **Every morning** ingest checks ESPN's scoring type against the lock. If they stop
  matching, the league keeps its data, every page shows a banner, and it stops
  refreshing until the site owner reloads it with `scripts/set_format.py`.
- **Point values stay live.** Only the format is locked; a commissioner's change to a
  stat's value shows up the next morning.
- **League settings** shows the locked format and season.
- Leagues registered before the lock were locked as categories by their next data load.
- Refused: roto and season-total points, and leagues whose point values change by
  lineup slot.

## The numbers

| Metric | How it's computed |
| --- | --- |
| **FP/G** | Fantasy points per game: ESPN's own number for the league's scoring (bonuses such as double-doubles included). If ESPN sends none for a window, League Lab's stat × points from the per-game line. *Blended* mixes season and projection: alpha = min(season games / 20, 1). |
| **PAR** | Points above replacement: FP/G minus the median FP/G of the 10 best healthy free agents in that window. |
| **Projected points a week** | Each day, the best legal lineup from the players with an NBA game: the league's lineup slots, each player's eligible slots. Averaged over the rest of the regular season. Injured players count from the week they're expected back (ESPN's date, else IR 4 weeks, OUT 2, day-to-day 1). IR players are left out. |
| **Expected wins a week** | Each team's weekly points as a bell curve with the league's week-to-week spread σ; the chance of outscoring each other team, added up (out of teams − 1). |
| **σ (week-to-week spread)** | How far teams' weekly scores fall from their own average, once 3 weeks are played; 12% of an average week until then. |
| **All-play** | Each week a team beats every team it outscored. Power Rankings rank on all-play win %. |
| **Luck** | Actual win % minus all-play win %, season to date. |
| **Projected finish** | Weeks played as they happened; every remaining regular-season matchup won with chance Φ((μ₁ − μ₂) / (σ√2)). The current week adds the points already scored to the projection for the days left. |
| **Points by source** | Each stat's per-game points grouped into Scoring, Threes, Rebounds, Assists, Steals and blocks, Misses and turnovers (any negative value), and Other (bonuses ESPN counts that the stat line doesn't show). |

ESPN's applied points are the source of truth. Each run compares them with League
Lab's stat × points for every player and window and records how many differ by more
than 0.1 (`points_check` in the registry).

## Pages

| Page | In a points league |
| --- | --- |
| **Home** | Standings with record, points for and against; this week's scores |
| **Compare** | *Teams*: projected points and expected wins, the chance one outscores the other in a week, weekly scores, points a week by source. *Players*: up to 4 players' FP/G in every window, PAR, games, health, and points per game by source |
| **Power Rankings** | All-play record and win %, points a week, luck; projected record, projected points and expected wins a week |
| **Matchups and Luck** | Each week's scores and margins, the highest scores in a loss, luck |
| **Transactions** | Unchanged |
| **Roster Strength** | Teams by projected points a week, this week's projection and games, bench FP/G, expected wins; points a week by source; each team's lineup (starts and points a week per player) |
| **Trade Analyzer** | Below |
| **Player Rankings** | Every player by FP/G with PAR, games this week, season points and each stat's points per game; filters for free agents, rostered, your team, and slot |
| **Draft** | Your best pick at every turn, judged against the rosters every other team is building; live drafts and mock drafts. See [draft-guide.md](draft-guide.md) |

## Trade Analyzer

Every deal is judged by both teams' change in **expected wins a week**. A point is
worth the same to every team, so deals help both sides through lineups: open roster
spots, games per week, positions and injuries.

- **Team profile**: projected points a week and rank, expected wins, this week's
  projection, your lineup (starts and points a week per player), and who sits most.
- **Waiver wire**: add a free agent, dropping your player whose loss costs least (or
  nobody, with an open spot), ranked by expected wins.
- **Trade finder**: every 1-for-1, 2-for-1, 1-for-2 and 2-for-2 deal with every team
  that raises both teams' expected wins and isn't lopsided.
- **Create a trade**: *Offer Builder* (trade block of up to 6, any team or one, up to
  3 each way, Win-win / Close call / Max gain) and *Search by player* (every deal that
  brings him over, labelled Likely to work / Costs you / They'd likely say no).
- **Mock trade**: any trade or waiver move with your own adds and drops; both teams'
  points a week and expected wins before and after, and your lineup after.

Rules carried over from categories leagues:

| Rule | Points version |
| --- | --- |
| Acceptance | Win-win: partner's expected wins don't fall, not lopsided. Close call: falls by at most 0.2 a week, not lopsided. Max gain: no limit, lopsided flagged. You must gain in all three. |
| Lopsided | The season value a team gives (PAR, at least 0, × games left) beats what it gets by more than 25% of the larger side. |
| Rosters stay full | A team getting extra players drops those it expects the fewest points from the rest of the way (FP/G × games left), never one it just received; a team left short adds the best healthy free agents. |
| Search size | Offer Builder refuses any search over 250,000 deals before it starts. At most 3 offers per team when searching every team. |
| Near-duplicates | A deal is dropped when the same deal minus a player you get gains you as much. |

**Two speeds.** Searches score every deal with a fast estimate (positions ignored:
each day the best S players with a game start, worked out exactly from each player's
chance of playing). The best 40 deals, plus the best 10 per partner (or per label in
Search by player), are rescored with the full daily lineup simulation, re-filtered
and re-sorted; those are the numbers shown, and the ones Mock trade gives for the
same deal. A test checks that the two estimates rank deals alike.

**Pitches** are written from the other manager's side: "This adds about 7.4 points a
week to your lineup: you'd get Neemias Queta (27.2 FP/G, 3.1 games a week) and
Jonathan Kuminga (26.3 FP/G, 3.1 games a week) for CJ McCollum (32.4 FP/G, 2.9 games
a week). You'd drop Tim Hardaway Jr. to make room."

## Limits

- The NBA schedule is ESPN's: games not set yet (the NBA Cup knockout rounds in
  December) are missing until ESPN adds them; the schedule reloads every morning.
- Matchup weeks run Monday to Sunday from opening night until a week has been
  played; from then on ESPN's own days for that week are used.
- One league-wide σ for every team, not each team's own spread.
- Lineups assume the manager starts the best available players every day.
- Roto and season-total points leagues aren't supported.
