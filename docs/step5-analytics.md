# Step 5: Analytics layer

Step 5's job is to put every bit of real computation — pivots, simulated
head-to-heads, luck, z-scores — into BigQuery views, so Step 6's dashboard pages
only ever `SELECT` and plot. All 7 views are written and live in the `fantasy`
dataset.

## The finding that shapes every view here

Step 2's real `box_scores()` pull (back when validating `espn-api`'s actual field
shapes) showed this league scores 9 categories with **no turnovers**: FG%, FT%,
3PM, 3PT%, REB, AST, STL, BLK, PTS. The original proposal assumed a 9-category
league *with* turnovers (the standard "9-cat" format). Every view below is built
on the real category set, not the assumed one — there's no "lower is better"
category to special-case anywhere in this layer.

One consequence that rippled back into Step 3: `player_stats` didn't originally
have a `fg3a` (3-point attempts) column, because the proposal's column list didn't
include it. But 3PT% is a real scoring category here, and a percentage can't be
recomputed from makes alone — it needs attempts too. `fg3a` was added to both the
DDL and `ingest/transform.py`'s `CATEGORY_COLUMNS` map before `v_team_roster_stats`
could be built correctly.

## Build order (each view's real dependency chain)

```
matchup_categories (raw table)
        │
        ▼
v_team_week_cats  ──────────────┐
        │                        │
        ▼                        ▼
v_all_play                  (feeds Compare page directly)
   │        │
   ▼        ▼
v_power_rankings   v_luck (also reads matchup_categories + teams directly)

transactions (raw table) ──► v_transactions

rosters + player_stats (raw tables)
        │
        ▼
v_team_roster_stats ──► v_roster_strength
        │
        └──► (feeds Trade Analyzer page directly)
```

`v_team_week_cats` and `v_team_roster_stats` are the two foundational views —
everything else in their branch builds on top of them rather than re-deriving
category math from the raw tables a second time.

## The views, in dependency order

### `v_team_week_cats`
**Grain:** team × matchup_period. **Feeds:** Compare page, and `v_all_play`.

Pivots `matchup_categories` (long format: one row per team/week/category) into one
row per team-week with all 9 categories as columns. FG%/FT%/3PT% are recomputed as
`SAFE_DIVIDE(makes, attempts)` — never ESPN's own stored percentage rows, which get
pivoted in but then ignored on purpose. `SAFE_DIVIDE` leaves a percentage `NULL`
on 0 attempts (e.g. before any games), rather than erroring or returning 0 and
lying about shooting 0%.

### `v_all_play`
**Grain:** team × matchup_period. **Feeds:** `v_power_rankings`, `v_luck`.

The "what if this team played everyone this week" simulation. Unpivots
`v_team_week_cats`'s 9 category columns back to long format, self-joins every team
to every other team in the same week on category, and counts how many categories
each side would have won. A `NULL` percentage (0 attempts, so it can't be compared)
counts as a tied category rather than silently dropping the comparison —
`UNPIVOT INCLUDE NULLS` keeps those rows instead of filtering them out. Ties count
as half a win in both the matchup-level win % (`ap_win_pct`) and the raw
category-level win % (`ap_cat_win_pct`), so a team that goes 0-0-13 (all ties) in
week 1 shows exactly 0.5, not 0 or undefined.

### `v_power_rankings`
**Grain:** team × matchup_period, where every number is a running season-to-date
total through that week. **Feeds:** Power Rankings page.

Windowed `SUM(...) OVER (PARTITION BY season, team_id ORDER BY matchup_period)`
over `v_all_play`'s weekly numbers. That one running-total shape serves both of the
page's visuals without two separate queries: filter to the latest week for the
ranked table, or keep every week for the rank-over-time line chart. Ranked by
`RANK()` on all-play win %, with all-play category win % as the tiebreak. Team
names are joined from each team's *latest* snapshot (via a
`QUALIFY ROW_NUMBER() ... = 1` dedup pattern reused in three other views below), so
a mid-season team rename shows the current name retroactively across every week,
not the name they had back then.

### `v_luck`
**Grain:** team × matchup_period. **Feeds:** Matchups and Luck page.

Luck is actual result minus all-play result — how much better or worse a team did
against its real one opponent than it would have against the whole league that
week. The actual result is rebuilt from ESPN's own per-category `result` field
(`W`/`L`/`T`), filtered to the 9 real scoring categories — not a second
recomputation of who-beat-who, since ESPN's own verdict is the actual result by
definition. That gets joined against `v_all_play`'s simulated win % for the same
team-week. `luck_week` is that single week's gap; `luck` is the average gap
season-to-date (a windowed `AVG(...) OVER (PARTITION BY season, team_id ORDER BY
matchup_period)`), which is the number the luck bar chart actually shows — a team
that got unlucky once and lucky twice should show as net lucky, not as whatever
one week happened to be.

### `v_transactions`
**Grain:** one row per transaction action (same grain as the raw `transactions`
table). **Feeds:** Transactions page.

Mostly a pass-through with two additions. First, ESPN's raw action strings
(`'FA ADDED'`, `'WAIVER ADDED'`, `'DROPPED'`, `'TRADED'`) are kept verbatim as
`action` for the activity-log table, and folded into a normalized `action_type`
(`ADD`/`DROP`/`TRADE`/`OTHER`) for the page's filter dropdown and per-team bar
chart — `OTHER` is a deliberate catch-all so an action label ESPN adds later
doesn't silently vanish from the view, it just shows up unfiltered instead of
breaking. Second, each team's running `team_adds`/`team_drops`/`team_trades`/
`team_txn_count` ride along on every one of that team's rows as window function
totals (`COUNT(*) OVER (PARTITION BY season, team_id)`), so the page's per-team bar
chart needs no `GROUP BY` of its own — it reads the count straight off any row.

### `v_team_roster_stats`
**Grain:** player × stat_window, for the *latest* roster snapshot only. **Feeds:**
Trade Analyzer page directly, and `v_roster_strength`.

Joins each team's current roster to every player's per-game stat line across every
`stat_window` (not just one), because the Trade Analyzer and Roster Strength pages
both need to switch between 7/15/30-day and season windows, and before the season
starts only `'projected'` has real data at all. Deliberately **not** z-scored —
unlike `v_roster_strength` below, a trade's before/after/delta comparison is
between two specific rosters' own raw numbers, not league-relative ones; z-scoring
would turn "gained 3 rebounds a night" into an unreadable standard-deviation
figure. Makes and attempts ride along next to every percentage (`fg3a` alongside
`fg3_pct`, etc.) for exactly the same reason as `v_team_week_cats`: when the app
sums several players into a combined roster total, it must recompute
`SUM(makes)/SUM(attempts)`, never average the players' individual percentages. A
player with no stats in a given window just has no row for that window, rather
than a row full of zeroes that would silently drag down a sum.

### `v_roster_strength`
**Grain:** team × stat_window. **Feeds:** Roster Strength page.

Built directly on `v_team_roster_stats` rather than re-joining `rosters` and
`player_stats` itself, so the roster-to-stats join logic exists in exactly one
place. Sums each roster's players into team totals (counting stats summed
directly; FG%/FT%/3PT% recomputed from summed makes/attempts, same rule as every
other view here), then z-scores each category across the league for that window:
`SAFE_DIVIDE(team_value - AVG(...) OVER window, STDDEV_POP(...) OVER window)`.
Every `*_z` column is how many standard deviations that team sits above (+) or
below (−) the league average — the heatmap's actual values. Since all 9 categories
are "higher is better" here (no turnovers to flip the sign on), no category needs
special-casing in the z-score math. Players in the `IR` lineup slot are excluded —
they aren't on the active roster contributing stats, so including them would
overstate a team's real strength.

## Patterns reused across views

- **Latest-snapshot dedup**: `teams` and `rosters` both accumulate a new row per
  day (Step 3's design). Four views (`v_power_rankings`, `v_luck`,
  `v_team_roster_stats`, `v_transactions`) need *current* team names or rosters,
  not history, so each uses the same
  `QUALIFY ROW_NUMBER() OVER (PARTITION BY season, team_id ORDER BY snapshot_date DESC) = 1`
  pattern to grab just the latest row per team.
- **Ties as half a win**: `v_all_play` and `v_luck` both treat a tied category (or
  a tied simulated matchup) as 0.5 toward a win percentage, never as a 0 or as an
  excluded row — otherwise early-season weeks full of 0-0 ties (every team's real
  state right now, pre-season) would show as undefined or artificially low
  percentages instead of the correct 0.5.
- **Makes/attempts over stored percentages, everywhere**: `v_team_week_cats`,
  `v_team_roster_stats`, and `v_roster_strength` all recompute FG%/FT%/3PT% from
  `SAFE_DIVIDE(makes, attempts)` rather than trusting or averaging any stored
  percentage value. This is Step 3's original design principle, carried all the way
  through the analytics layer rather than only applying at the raw-table level.

## Verification

Every view was created directly against the live `fantasy-dash-emk.fantasy`
dataset (not just checked for valid syntax) and queried for sane output:

- `v_team_week_cats` / `v_all_play`: all teams currently show `NULL` percentages
  and all-tied 0.5 win%/category-win% — correct, since every team is still at
  literally zero real stats pre-season.
- `v_power_rankings`: every team ranks `1` with `ap_win_pct = 0.5` for the same
  reason — a real tie, not a bug.
- `v_luck`: every matchup shows `actual_result = 'T'` and `luck_week = luck = 0.0`
  — again, correctly reflecting that nothing has actually been decided yet.
- `v_roster_strength` / `v_team_roster_stats`: these two *do* show real non-zero
  numbers right now, because they're built on `'projected'` stats rather than
  in-season results — e.g. real per-game point projections and real positive/
  negative `pts_z` values spread across teams, proving the join and z-score math
  work correctly end to end even before the season starts.
- `v_transactions`: shows the one real transaction in the league so far (the
  user's own team dropping Russell Westbrook), with `action_type = 'DROP'` and
  `team_drops = 1` correctly computed.

## Done when

All 7 views exist in BigQuery, each returns rows that match hand-checkable
expectations for the league's current (pre-season) state, and none of them
duplicate computation that another view in the chain already did. All of that
holds today — Step 5 is complete. The real test still ahead is re-verifying
`v_all_play`, `v_power_rankings`, and `v_luck` once actual games are played and
results stop being all-ties — that's the first point these views will produce
genuinely interesting (non-symmetric) output to sanity-check by hand against
ESPN's own site.
