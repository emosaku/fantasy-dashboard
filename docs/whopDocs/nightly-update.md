# LeagueLabWhop: the nightly NBA update

**Status: done and deployed to `league-lab-whop` (October 29, 2026).** This is step 2 of
the remaining timeline. Every player number the pages show now comes from our own data:
actual stats, projections, games-played history and injuries. ESPN supplies only the
customer's league (settings, teams, rosters, matchups, activity, free agents) and the
NBA schedule. Next is step 3, accounts and payment ([product.md](product.md)).

## What runs each morning

```
05:00 Phoenix   nba-nightly (new)                     BallDontLie + ESPN's player list
                  1. yesterday's games      ──►  nba_player_games
                  2. new players            ──►  nba_players
                  3. link new ESPN ids      ──►  nba_players
                  4. in-season blend        ──►  projections (kind "blended")
                  5. games-played history   ──►  player_seasons
                  6. injuries               ──►  nba_injuries
05:30 Phoenix   league-ingest (changed)              ESPN, per league
                  reads all of the above once per run, writes each league's
                  player_stats, player_points, rosters, free_agents, player_details
```

1. **Games.** The season's finished games since the last load, plus the 3 days before it
   again to pick up late stat corrections. With nothing loaded yet, the whole season so
   far: the first run caught up the season's first 9 days (68 games).
2. **New players.** Anyone in those games that `nba_players` doesn't know is added.
3. **Linking.** This season's players without an ESPN id are matched by name to ESPN's
   public player list. Ids already linked are never changed or reused. The first run
   linked 49 rookies and call-ups (Cooper Flagg, Dylan Harper ...). Still unlinked:
   Jaylin Williams (two players share the name) and David Jones.
4. **In-season blend.** The preseason projection mixed with the season so far
   ([projections.md](projections.md#in-season)). The pages' "projected" window is now
   this rest-of-season line, refreshed every night. Projected games are for the whole
   season (played so far plus his share of his team's remaining games), as before.
5. **Games-played history.** The last 3 seasons' games played, by ESPN id, from our own
   games. Replaces ESPN's per-league history fetch.
6. **Injuries.** BallDontLie's injury list: status and expected return date only. Its
   written injury notes are someone else's reporting and aren't kept.

## How the blend behaves

The preseason line counts as 600 minutes of play for the rates and 15 games for
minutes per game. A hot or cold first week moves a veteran a little, and by the
All-Star break his own season dominates:

| Player | Preseason pts | Games | So far | Blended |
|---|---|---|---|---|
| Ty Jerome | 14.1 | 4 | 29.8 | 16.6 |
| Mikal Bridges | 15.5 | 5 | 5.0 | 13.2 |
| Shai Gilgeous-Alexander | 30.6 | 5 | 26.0 | 29.6 |
| Giannis Antetokounmpo | 25.4 | 5 | 27.6 | 25.9 |

**Rookies** have no preseason projection, so they start from a league-average line
(18 minutes, last season's league rates). Their own minutes take over faster than a
veteran's: the prior counts as 5 games, not 15. That setting came from testing on the
2024-25 and 2025-26 rookie classes, projecting the rest of the season from the first
9, 21 and 45 days:

| Rookie setting | Error after 9 days | 21 days | 45 days |
|---|---|---|---|
| His own early numbers alone | 7.9 | 6.7 | 5.9 |
| Minutes prior of 15 games (the veteran setting) | 5.5 | 4.9 | 4.8 |
| **Minutes prior of 5 games (used)** | **4.8** | **4.7** | **4.5** |

(Mean error in fantasy points per game, ESPN default scoring, weighted by minutes.)
Rookies still run about 2 points a game low, because rookies get better during the
season. Example today: Yaxel Lendeborg, 22.6 points in 34 minutes over 5 games,
projected 13.5 in 26 minutes.

## What changed in the league ingest

| Data | Before | Now |
|---|---|---|
| Stat windows (season, last 30/15/7) | ESPN | Ours, from BallDontLie games |
| Fantasy points for those windows | ESPN's (`source = espn`) | Ours: our line times the league's point values (`source = computed`) |
| Injury status and return date (rosters, free agents, health) | ESPN | BallDontLie's injury list. A player not on it is healthy |
| Games-played history | ESPN, per new player | Ours, written nightly |
| Projected window | Our preseason line | Our blended line, nightly |

ESPN's fantasy points are still read, in memory only, as a check: the points league's
`points_check` now compares ESPN's numbers with ours.

## Checked against ESPN

The real league ingest ran on the same two public leagues as before (Utah Pro H2H
Points, Brooklyn Pro H2H Most Categories) in a throwaway dataset, since deleted:

- **Every player ESPN shows games for is in our windows** (866 and 878 player windows,
  none missing).
- **Games played, points, field goals, free throws and threes match ESPN exactly.**
- **Minutes differ slightly** for most players: ESPN rounds each game to whole minutes,
  BallDontLie keeps the seconds (Dylan Harper: 32.2 vs 32.6).
- **About 2% of other values differ by one rebound, assist or steal**: the two
  providers' stat corrections. In the points league that's 103 of 866 player windows
  flagged by the check, every one from such a difference and none from our math. Each
  is about 1 fantasy point a game now and will shrink as games accumulate.
- The pages' precomputed tables (`m_player_pool` and the rest) carry all five windows,
  injuries (17 out, 4 day-to-day per league) and history for 442 of 469 players.

## Deployed

| Piece | Where |
|---|---|
| `nba-nightly` Cloud Run Job | Same image as `league-ingest`, command `python -m ingest.projections.nightly`; ran clean in the cloud |
| `nba-nightly-daily` schedule | 05:00 America/Phoenix, half an hour before `league-ingest-daily` |
| Alert | "LeagueLabWhop nba-nightly failed", same email channel as the ingest alert |
| `league-ingest` | Redeployed with the new windows, points and injuries |
| `league-lab` site | Redeployed (`league-lab-00003-nht`): text no longer credits ESPN for injuries or fantasy points |
| `nba_injuries` table | New: `sql/ddl/18_nba_injuries.sql` |
| `scripts/teardown.py` | Now pauses both schedules |

If the nightly job fails, the pages keep the previous day's numbers and the alert emails.
The cost is about 25 BallDontLie requests a night (well under ALL-STAR's 60 a minute)
and small BigQuery reads.

## Code

| Where | Change |
|---|---|
| `ingest/projections/nightly.py` *(new)* | The job: games, players, linking, blend, history, injuries |
| `ingest/projections/source.py` | Unfinished games skipped; players by id; the schedule (`games_left`); injuries |
| `ingest/projections/run.py` | `windows` and `injuries` readers for the league ingest |
| `ingest/transform.py` | `transform_window_stats`, `transform_window_points`, `apply_injuries`; the points check compares ESPN with ours; ESPN's stat windows and games-history transforms removed |
| `ingest/main.py` | Reads our data once per run (`Ours`), no more ESPN history fetch |
| `ingest/espn_client.py` | `fetch_player_history` removed |
| Tests | 300 pass: new tests for the nightly steps, windows, points, injuries and the BallDontLie additions |

## Running it by hand

```bash
# The nightly update (AS_OF defaults to yesterday, US Eastern)
GCP_PROJECT_ID=league-lab-whop SEASON=2027 python -m ingest.projections.nightly
# or in the cloud
gcloud run jobs execute nba-nightly --region us-west1 --project league-lab-whop
```

## Known gaps

1. **Rookies run about 2 fantasy points a game low** (above). A rookie model using draft
   slot and college stats is still a later item.
2. **Two players aren't linked** (Jaylin Williams, David Jones), so they show no stats.
   One manual alias each would fix it if they matter to a customer's league.
3. **Bonus stats** (double-doubles, triple-doubles) count 0 in a points league, as
   before; the points check flags players who earn them.
4. **The NBA schedule still comes from ESPN** for the points pages; BallDontLie's
   schedule is now loaded too, so swapping it is a small later change.
