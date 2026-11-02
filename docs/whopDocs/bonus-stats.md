# LeagueLabWhop: fantasy bonus stats (double-doubles and more)

**Status: done and deployed to `league-lab-whop` (November 1, 2026).** Online copy:
https://claude.ai/artifact/63odHQ6stpGnL6gyYxvSUj.

## Summary

League Lab now counts every bonus our box scores can supply: double-doubles,
triple-doubles, quadruple-doubles, personal fouls, foul-outs and missed shots. Before,
any stat outside our 15 per-game stats counted 0, so a league paying for double-doubles
undervalued big men by up to about 4 fantasy points a game, with no warning.

A bonus can't be worked out from averages (12 points and 9 rebounds a game could mean
30 double-doubles or none), so it's counted game by game from the box scores we now
store. Four stats ESPN offers still can't be counted, because our stats source doesn't
report them: ejections, flagrant fouls, technical fouls and games started (and TW,
probably team wins). Each league records which of its scored stats we can't count, and
the user is told rather than having them silently treated as 0.

## Every stat outside the core 15

| ESPN stat | What it is | How we get it | Counted now |
|---|---|---|---|
| DD (double-double) | 10+ in two of points, rebounds, assists, steals, blocks in a game | Counted per game from our box scores | Yes |
| TD (triple-double) | 10+ in three | Same | Yes |
| QD (quadruple-double) | 10+ in four | Same | Yes |
| FGMI, FTMI, 3PMI (misses) | Shots missed | Attempts minus makes | Yes |
| PF (personal fouls) | Fouls committed | BallDontLie's box score, now stored | Yes |
| DQ (fouled out) | Six fouls in a game | Counted per game from fouls | Yes |
| EJ, FF, TF | Ejections, flagrant fouls, technical fouls | Not in BallDontLie's data | No: shown as not counted |
| GS (games started) | Starts | Not in BallDontLie's data | No: shown as not counted |
| TW | ESPN stat 43, probably team wins | Could come from game scores | Not yet: no league seen scores it, so ESPN's meaning can't be checked |
| Rate stats (FG%, APG, PPM ...) | Averages and percentages | From the core stats | Already supported as categories |

ESPN's default points scoring uses none of these; they matter in custom leagues.

## How the fix works

1. **Counted game by game:** double-, triple- and quadruple-doubles (a triple-double
   also counts as a double-double, as on ESPN); a foul-out at 6+ fouls; misses as
   attempts minus makes (`ingest/projections/games.py`, `with_bonus`).
2. **Averaged like any stat:** a window's DD value is the share of games with one (0.6 =
   60%), so a league paying 5 per double-double adds 0.6 x 5 = 3 points a game.
3. **Projected from his own rate** (`ingest/projections/bonus.py`): this season's games
   3x, last season 1x, the season before 0.5x, pulled toward the league rate by 10
   games. Tested on 2024-25 and 2025-26: about 0.045 mean error in double-double share,
   as good as repeating last season preseason and 6% better once 10-25 games are in;
   3x on this season beat 1x and 2x. Misses come from projected attempts and makes.
4. **Points leagues:** the extra stats are in actual and projected fantasy points.
5. **Categories leagues:** DD, TD, QD, PF, DQ and the misses are now accepted as
   categories (`ingest/catalog.py`, `EXTRA_COUNT`).
6. **Games played as a scored stat** now scores once per game (it was multiplied by the
   window's game count).

Personal fouls were added to `nba_player_games` (this season and the two before were
reloaded) and five bonus columns to `projections`.

## Making sure each custom league is counted right

**Per-league flags, read automatically from the league's ESPN scoring every morning,
never set by hand**, backed by a nightly check against ESPN's own numbers. Hand-set
flags would go stale when a commissioner changes scoring mid-season; ESPN sends each
league's full scoring rules on every refresh, so the flags are those rules.

| Safeguard | What it does | Status |
|---|---|---|
| Scoring re-read each morning | A bonus added mid-season is counted from the next morning | In place |
| Uncounted stats per league | Each refresh records `uncounted_stats` on the league | Built |
| Sign-up warning | Points league: accepted, with a warning naming the uncounted stats. Categories league with such a category: refused | Built |
| Nightly check against ESPN | ESPN's fantasy points per player compared in memory with ours; gaps above 0.1 a game flagged (`points_check`). ESPN's points for stats we can't count are taken off its side first, and only windows where both count the same games are compared (during the day ESPN already has tonight's games) | Built |
| Alert on a jump | More than 25% of comparable windows off (at least 50 checked): the ingest logs a `POINTS_CHECK_ALERT` line and the "LeagueLabWhop points check off" policy emails the alert channel (at most hourly). Normal is the providers' small stat corrections: 13% on the live test league today | Built Nov 1 (R8a) |
| Note on the pages | Uncounted stats named under the title of every points page | Built Nov 1 (R8b) |
| Weekly total check | ESPN's weekly team scores against our starters' points | Backlog P5, after release |

## Checked against ESPN

237 players from the two public test leagues; compared where both sides have the same
games (790 of 878 player windows; the rest only because ESPN already had that
afternoon's games):

| Stat | Compared | Equal to ESPN | Largest gap |
|---|---|---|---|
| DD, TD, QD, PF, FTMI | 790 each | 790 each | 0 |
| FGMI | 790 | 759 | 0.33 a game (one attempt) |
| 3PMI | 790 | 776 | 0.33 a game (one attempt) |
| DQ | 790 | 780 | 0.25 a game |

Missed-shot gaps are single attempts the providers record differently. Foul-outs agree
for 13 of 16 players; in three games both show six fouls but ESPN counts no foul-out,
for reasons the data doesn't show. With bonus-heavy test scoring (DD +5, TD +10, PF −1,
FGMI −1, DQ −5), 106 of 880 player windows differ from ESPN by more than 0.1 a game,
all from those one-attempt gaps (largest 1.5 over a short window).

Top projected double-double rates: Jokic 78% (triple-doubles 46%), Towns 75%, Sabonis
71%, Giannis 61%, Wembanyama 60%.

## Still open

| Item | When |
|---|---|
| Ejections, flagrant and technical fouls, games started, team wins (P8) | After release |
| Weekly total check (P5) | After release |
| The three foul-outs ESPN doesn't count: check against official box scores | When a customer league scores foul-outs |
