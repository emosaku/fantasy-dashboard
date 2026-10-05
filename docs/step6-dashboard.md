# Step 6: Streamlit dashboard

Step 5 builds the views; Step 6 is the only step that's actually frontend — a
multipage Streamlit app that reads those views and renders them. This is what the
league actually opens on their phones once Step 7 deploys it.

All six pages are built and run locally against the live BigQuery views:

```bash
streamlit run app/Home.py   # from the repo root, so .streamlit/config.toml is picked up
```

## Architecture

```
Browser
   │
   ▼
Streamlit app (Cloud Run service, Step 7)
   │  app/Home.py: st.navigation multipage layout, standings, "last updated" note
   ▼
app/pages/*.py  -- one file per page: controls + charts, no SQL, no stats math
   │
   ├──► app/queries.py  -- one function per view, the only place SQL lives.
   │       @st.cache_data(ttl=3600) on every read -- data only changes once a day,
   │       so page clicks never re-hit BigQuery
   │
   └──► app/categories.py, compare.py, trade.py  -- the app's own math, plain pandas
           (no Streamlit, no BigQuery), so it's unit-tested in tests/app/
   ▼
BigQuery views (Step 5)
```

| File | What it holds |
|---|---|
| `app/Home.py` | Entry point: page config, `st.navigation` with all six pages, standings table, the sidebar freshness note |
| `app/queries.py` | `teams()`, `last_updated()`, and one function per view. Every query is limited to the latest season; team names are whitespace-stripped (ESPN keeps trailing spaces, which break Markdown bold) |
| `app/categories.py` | The 9 categories, display formatting (`.471`, `112.2`), and `totals()` — the one rule for combining stat lines: sum counting stats and makes/attempts, then recompute percentages |
| `app/compare.py` | Compare's week/season stat lines, league z-scores, head-to-head category count |
| `app/trade.py` | Trade Analyzer's before/after/delta |
| `app/ui.py` | Chart colors per light/dark theme, shared Plotly layout, `table_height()`, sidebar note |
| `.streamlit/config.toml` | Blue accent color per theme (see "Color" below) |

## The six pages

| Page | Controls | Visuals | Reads |
|---|---|---|---|
| **Compare** | two teams; season or one week | one-line verdict ("would beat X 6-3-0"); radar of category z-scores with a league-average ring; 3×3 small multiples of the raw values; table view | `v_team_week_cats` |
| **Power Rankings** | week slider (once there are 2+ weeks) | ranked table with all-play record, win %, category win %, rank movement; rank-over-time line chart with up to 3 highlighted teams | `v_power_rankings` |
| **Matchups and Luck** | week picker | one scoreboard card per matchup (winner named, higher value bold); season-to-date luck bar chart; luck table | `v_luck`, `v_team_week_cats` |
| **Transactions** | team filter, action filter | stacked adds/drops/trades per team; activity log in Arizona time | `v_transactions` |
| **Roster Strength** | stat window (7/15/30 days, season, projected) | team × category heatmap: color is the z-score, the number in each cell is the real value; table view | `v_roster_strength` |
| **Trade Analyzer** *(added)* | your team, trade partner, stat window; click players | both rosters with per-game stats; who each side sends; before/after/change table for each side | `v_team_roster_stats` |

### Choices made along the way

- **Compare's z-scores are computed in the app** (`compare.py`), not in a view. The
  period (one week, or the season) is a page control, and z-scores depend on which
  period is selected. Season mode uses per-week averages for counting stats (teams
  may have played different numbers of weeks) and pools makes/attempts for
  percentages.
- **Compare's bars start at zero.** Two teams' FG% (.454 vs .463) look nearly equal
  as bars — honestly so. The radar above them is where differences show up, and
  every bar is labelled with its value.
- **Rank over time highlights 3 teams, not 14.** Fourteen colored lines can't be told
  apart. Everyone else is drawn as a thin gray line, and the top 3 at the selected
  week are highlighted by default (changeable, up to 3).
- **The scoreboard's category score is ESPN's own** (from `v_luck`), so it always
  matches ESPN's matchup page. The values shown per category are the recomputed
  ones from `v_team_week_cats`.
- **Luck is season-to-date** through the chosen week — one week's luck is mostly
  noise; the running total is the story.
- **Roster Strength defaults to Last 15 days**, falling back to Projected until
  games have been played. The heatmap's color scale is fixed at ±2.5 SD so colors
  mean the same thing across windows.

## Trade Analyzer: the one page that breaks the "logic belongs in SQL" rule

Every other page reads a precomputed view and just plots it. Trade Analyzer can't
work that way, because which players are being traded is arbitrary and changes on
every click — there's nothing fixed to precompute.

- **UI flow:** pick "your team" and a trade partner (the partner list excludes your
  team) → each team's roster shows with per-game stats → click a player's row to put
  them in the trade (click again to take them out) → "The trade" section lists who
  each side sends, and both sides get a Before / After / Change table across the 9
  categories, plus "Better in N categories, worse in M."
- **Where the math happens:** `trade.py`. `v_team_roster_stats` supplies each player's
  per-game line once; the app removes the players sent, adds the players received,
  and re-totals the roster with the same `totals()` rule as everywhere else
  (percentages from summed makes/attempts, never averaged).
- **IR players count for nothing**, the same rule as `v_roster_strength`: trading away
  an injured player doesn't lower your totals, and trading for one doesn't raise them.
- **Selections reset** when either team or the stat window changes (each roster table
  is keyed by team and window), and on every new session — there's no login, so
  "your team" is just whichever team is picked.
- **Changes are marked ▲/▼ as well as green/red**, so the direction never relies on
  color alone. Higher is better in all 9 categories, so ▲ is always good.

## Implementation details that apply to every page

- **Caching:** every read goes through one `@st.cache_data(ttl=3600)` function in
  `queries.py`; the BigQuery client itself is an `@st.cache_resource`.
- **Freshness indicator:** the sidebar shows when ingest last wrote data
  (`MAX(ingested_at)` from `teams`, which every ingest run updates), in Arizona time.
- **Pre-season and empty states:** every page handles the league's current state —
  one week, all zeros — without errors: Compare says every team is level instead of
  drawing an empty radar, Power Rankings explains the line chart appears after week
  2, and the window selectors only offer windows that have data.
- **Mobile-first:** columns stack on a phone; tables are sized to show every row
  without scrolling inside a scrolling page; the Plotly toolbar is hidden.
- **9 categories, no turnovers:** every page takes its category list from
  `categories.py`, which follows `v_team_week_cats`'s actual columns.

### Color

Charts use the validated default data-viz palette, with separate steps for light and
dark mode (picked from Streamlit's active theme via `st.context.theme`):

- **Two-team and three-type charts** use the first three categorical colors (blue,
  orange, aqua) in fixed order — the three that stay distinguishable for colorblind
  viewers in every pairing. Colors follow the entity, not its position: on
  Transactions, Adds are always blue even when filtered.
- **Above/below average** (luck, roster heatmap) is a diverging blue ↔ red scale with
  a gray midpoint: blue is good, red is bad.
- **The app accent is blue**, not Streamlit's default red, so selected controls don't
  read as "bad". It's set per theme in `.streamlit/config.toml` — a top-level
  `primaryColor` would have pinned the whole app to light mode.

## Verification

- **Unit tests** — `tests/app/test_math.py`, 9 tests, every expected value worked out
  by hand: percentage pooling (1-for-1 plus 40-for-100 = 41/101, not 70%), missing
  stats as zero, season averages vs pooled percentages, z-scores (including the
  all-equal case), head-to-head with a `NaN`, and the trade before/after/delta both
  ways including IR players.
- **Every page on live data** — run headlessly with Streamlit's `AppTest` against the
  real BigQuery views: Home and all six pages render with no exceptions in the
  league's current pre-season state.
- **Every page on a realistic season** — live data is still all ties, so the app was
  also run with a synthetic 4-week season (real teams and rosters; made-up weekly
  stats, results and transactions) patched in from outside the repo, and every page
  was screenshotted in a real browser at desktop and phone width, in light and dark
  mode. That's how these were caught and fixed:
  - the radar had a white background in dark mode, and its axis labels collided
  - a team name with a trailing space broke the scoreboard's bold text
  - tables cut off at 10 rows of 14 teams
  - a top-level accent color forced light mode while charts drew dark-mode colors
  - "would win 0-9-0" for a team that loses every category
- **Trade Analyzer clicks** — driven in the browser: selecting players updates both
  sides; clicking a selected player again removes them; selecting from only one side
  shows "Nobody" for the other. The numbers were checked by hand (an IR player sent
  away changes nothing; both sides' changes mirror each other).

## Done when

All six pages run locally against BigQuery with `streamlit run app/Home.py` — real
data on every page, not placeholder text. **Done.** The remaining check needs real
games: once Week 1 has numbers, open Matchups and Luck and compare one scoreboard to
ESPN's matchup page.
