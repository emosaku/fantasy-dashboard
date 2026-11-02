# LeagueLabWhop: daily league snapshots (M1)

**Status: done and deployed to `league-lab-whop` (November 1, 2026).** The foundation of
the history moat ([moat.md](moat.md)): every morning's refresh now keeps a dated copy
of what it used to overwrite, so each league builds a day-by-day history ESPN doesn't
keep and a competitor can't rebuild later.

## What's kept each day

| Table | One row per | What it holds | Feeds |
|---|---|---|---|
| `snap_rosters` | league, day, team, player | Who was on each roster, lineup slot, injury status | Hindsight trade grading (M10), manager profiles (M6) |
| `snap_standings` | league, day, team | Record, points for and against, standing | Archives (M14), "deserved" standings over time |
| `snap_category_ranks` | league, day, window, team, category | Rank, value, gaps (categories leagues); Lock / Swing / Punt tiers are computed from these | Tier changes over time (M11) |
| `snap_player_z` | league, day, window, player, category | Each player's per-game value and z-score, season so far and projected (categories leagues) | Hindsight trade grading (M10) |
| `snap_player_points` | league, day, window, player | Fantasy points per game, season so far and projected (points leagues) | Hindsight trade grading (M10) |
| `nba_injury_history` | day, player | That day's NBA injury list (shared by every league) | Grading trades made around injuries |

**Not copied, because it can already be rebuilt for any date:** NBA stat lines
(`nba_player_games`), our projections (`projections` keeps every run), weekly results,
power rankings and luck (kept per week), and transactions.

## How it works

- **Leagues:** after each run's refresh of the precomputed tables, the same script
  replaces the day's snapshot rows for the leagues it just loaded
  (`ingest/materialize.py`, `snapshot_statements`). The day is the refresh's date in
  US Eastern time. A manual refresh later the same day replaces that day's rows, so a
  day is never doubled and always holds the latest state.
- **Injuries:** the nightly NBA update writes the day's list to `nba_injury_history`
  as well as `nba_injuries` (`ingest/projections/nightly.py`).
- **Explicit columns:** each snapshot copies a fixed column list, checked by a test
  against the table definitions (`sql/ddl/19_league_snapshots.sql`), so a change to a
  current-state table can't reshape the history.
- **Deletion:** a league deleted on request loses its snapshots too. Keeping history
  after a lapsed membership is M2.

## Checked

- On the two public test leagues in a throwaway dataset (deleted after): one day gave
  133 and 137 roster rows, 10 standings rows each, 560 category-rank rows and 3,664
  player-value rows for the categories league, and 450 player-points rows for the
  points league. Running the same day again left the counts unchanged; the next day
  added a second set.
- Deleting a league left 0 snapshot rows for it.
- Live: tables created, both jobs deployed and run clean; `nba_injury_history` has its
  first day (118 players). League snapshots start with the first registered league.

**Size:** about 4,500 rows per league per day, roughly 50 MB per league per season:
pennies of BigQuery storage. Each table is partitioned by day and clustered by league,
so reading one league's history scans only its rows.
