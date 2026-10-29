# LeagueLabWhop: our projections in the app

**Status: done and deployed to `league-lab-whop` (October 21, 2026).** Every page that
shows projected numbers now shows ours, built by the model in
[projections.md](projections.md), and nothing ESPN wrote (its projections or its
player outlooks) is stored or shown any more. This is step 1 of the remaining timeline;
step 2, the nightly current-season update, is done too ([nightly-update.md](nightly-update.md)).

## How it works

The pages already read a stat window named `projected`. Only where that window comes
from changed, so no page logic did:

```
nba_player_games ──► model (ingest/projections) ──► projections table
                                                        │  scripts/make_projections.py
nba_players (BallDontLie id ↔ ESPN id) ─────────────────┤
                                                        ▼
league-ingest, per league: player_stats / player_points, window "projected"
                                                        ▼
                Compare, Trade Analyzer, Roster Strength, Power Rankings, points pages
```

1. **Make the projections.** `scripts/make_projections.py --project league-lab-whop
   --season 2027` runs the model on every loaded season before 2026-27 and writes one
   run to `projections` (kind `preseason`, model version `2026.10.1`). Done for
   2026-27: 802 players, 796 linked to ESPN ids.
2. **Hand them to the ingest job.** At the start of each run, `league-ingest` reads the
   newest run (`ingest/projections/run.py`, `latest`), keyed by ESPN player id through
   `nba_players`.
3. **Write them per league.** For each league's pool (rostered players and free agents),
   `transform_projected_stats` and `transform_projected_points` (`ingest/transform.py`)
   write our line as the `projected` window of `player_stats` and `player_points`. A
   points league's projected fantasy points are its own point values times our line.
4. **ESPN's projections are no longer kept.** `"_projected"` is gone from the ESPN
   windows the transforms read, so ESPN's projected stats and projected fantasy points
   never reach a table.

## What changed in the code

| Where | Change |
|---|---|
| `ingest/projections/run.py` *(new)* | `make_preseason`, `latest`, the shared `load_history` |
| `scripts/make_projections.py` *(new)* | Writes a season's preseason projections |
| `ingest/transform.py` | ESPN's `_projected` window dropped; `transform_projected_stats`, `transform_projected_points` added; `season_outlook` dropped from `transform_player_details` |
| `ingest/main.py` | Reads our projections once per run and passes them to every league |
| `sql/ddl/09_player_details.sql`, `sql/views/10_v_player_profile.sql` | `season_outlook` removed (column dropped in `league-lab-whop`) |
| `app/views/1_Compare.py`, `app/views/6_Trade_Analyzer.py` | The "ESPN outlook" expanders removed |
| Help text on five pages | "ESPN's projection" now reads "our projection" |
| Tests | ESPN's projection and outlook are checked to be ignored; our projected rows, points and the preseason runner are covered (285 tests pass) |

## Fixes found on the way

Looking at the real numbers before shipping turned up three problems. All are fixed,
and the backtest was re-run after each:

| Problem | Cause | Fix |
|---|---|---|
| Two players got their fathers' birth dates (Gerald Henderson, Ray McCallum) | The exact-name pass found only the father (the son is "Jr." in Wikidata) and took him without checking | Every pass now rejects a birth date that can't be his: drafted outside 17-25, or outside 18-40 in his first NBA season. Coverage rose to 99.8% of minutes |
| LeBron James (41) got no age decline | The aging curve stopped at 38, so ages 39+ were treated as 38 | Range extended to 42, and each age pooled with its two neighbors on each side (single ages were noisy: +9% blocks at 33). Backtest slightly better |
| Stars were underprojected by ~4 fantasy points a game (Giannis at 22 points) | Minutes came from last season alone and were pulled toward 18 for everyone, so an injury-shortened season sank a star | Minutes are now pulled toward the player's own 3-season level. Bias on the top 50 cut to about −1.5 |

The last fix trades some per-game accuracy on bench players for accuracy on the
players fantasy managers care about. The backtest after all three fixes:

| 2025-26 | Our model | ESPN |
|---|---|---|
| Fantasy pts/game error | **4.69** | 4.71 |
| Season fantasy points error | **494** | 520 |
| Ranking of the top 150 | 0.743 | **0.776** |
| Bias on the top 50 (fantasy pts/game) | −1.9 | **−0.3** |

Still better than ESPN overall. ESPN is still closer on the very top players. Part of
that is how the bias is measured (picking the top 50 by what actually happened favors
players who overachieved, so any honest projection looks low on them), but not all of
it. Narrowing it is the first item for the next model version.

## Checked end to end

The real per-league ingest was run against two public ESPN leagues (Utah Pro H2H
Points, Brooklyn Pro H2H Most Categories) in a throwaway dataset, deleted afterwards:

- The `projected` values the pages read equal our projections and differ from ESPN's
  (Jokić: 26.3 points in 34.8 minutes, ours; ESPN's 28.3 isn't stored anywhere).
- The points league's own check against ESPN's actual fantasy points passed (696
  player windows, 0 mismatches).
- The precomputed tables the pages read (`m_player_pool` and the rest) carry the
  `projected` window.
- About 13 players per league have no projection from us: the 2026 draft class (Cameron
  Boozer, AJ Dybantsa, Darryn Peterson ...), who have no NBA history yet, and one
  ambiguous name (Jaylin Williams). Until they play, the pages have no projected line
  for them; once they do, their season stats appear as usual.

Deployed: `league-ingest` and `league-lab` (revision `league-lab-00002-r96`) in
`league-lab-whop`; the site's health check passes and the deployed job ran cleanly
(no leagues registered there yet).

## Known gaps

1. **Rookies aren't projected.** A rookie model (draft slot and college or overseas
   stats) is a later item; until then the pages show nothing projected for them.
2. **Stars still run a little low against ESPN** (above).
3. ~~**Preseason only.**~~ Fixed October 29: the nightly update blends in the season so
   far ([nightly-update.md](nightly-update.md)).
4. **A points league's stats outside the 15 we project** (fouls, double-doubles) count 0
   in projected fantasy points, as decided for the stats source.

## Running it

```bash
# A season's preseason projections (once a season, or after a model change)
python scripts/make_projections.py --project league-lab-whop --season 2027
# Re-check the model whenever it changes
python scripts/backtest_projections.py --project league-lab-whop --seasons 2024 2025 2026 --espn
```

After a model change, bump `MODEL_VERSION` in `ingest/projections/run.py` and
redeploy the ingest job (`gcloud run jobs deploy league-ingest --source ingest
--region us-west1 --project league-lab-whop`); the next run picks up the newest
projections.
