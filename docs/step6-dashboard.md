# Step 6: Streamlit dashboard

Step 5 builds the views; Step 6 is the frontend — a multipage Streamlit app behind
manager logins that reads those views and renders them, plus the analysis that reacts
to page controls (the trade/waiver search and the season projection). This is what
the league opens on their phones once Step 7 deploys it.

Everything is built and runs locally against the live BigQuery views:

```bash
python scripts/manage_logins.py   # once: create the managers' logins
streamlit run app/Home.py         # from the repo root, so .streamlit/ is picked up
```

## Architecture

```
Browser
   │
   ▼
Streamlit app (Cloud Run service, Step 7)
   │  app/Home.py: login gate, st.navigation, standings, sidebar (who's signed in,
   │  "Data updated", Refresh data)
   ▼
app/pages/*.py  -- one file per page: controls + charts, no SQL
   │
   ├──► app/queries.py      -- one function per view, the only place SQL lives;
   │                            every read cached for an hour
   ├──► app/analysis/       -- trade/waiver analyzer + season projection: plain
   │                            pandas/numpy, no Streamlit, unit-tested
   ├──► app/categories.py, compare.py, trade.py  -- shared stat math, unit-tested
   └──► app/refresh.py      -- Refresh data: runs the espn-ingest Cloud Run Job
   ▼
BigQuery views (Step 5)
```

| File | What it holds |
|---|---|
| `app/Home.py` | Entry point: page config, the login gate, `st.navigation`, standings, the sidebar |
| `app/login.py`, `app/auth.py` | The login page and session; password hashing (scrypt), checking and lockout |
| `app/queries.py` | One function per view plus `teams()`, `last_updated()`, `league_status()`. Every query is limited to the latest season; team names are whitespace-stripped |
| `app/categories.py` | The 9 categories, display formatting (`.471`, `112.2`), and `totals()` — sum counting stats and makes/attempts, then recompute percentages |
| `app/compare.py` | Compare's week/season stat lines, league z-scores, head-to-head count |
| `app/trade.py` | The mock trade's per-game before/after/delta |
| `app/analysis/` | `pool`, `weights`, `objective`, `waivers`, `trades`, `explain` (the Trade & Waiver Analyzer), `projection` (Power Rankings' projected finish) and `rankings` (Player Rankings) |
| `app/analyzer.py` | Cached glue between the z-score views and `app/analysis/` |
| `app/refresh.py` | Runs the ingest job through the Cloud Run API and waits for it; 10-minute cooldown |
| `app/ui.py` | Chart colors per light/dark theme, shared Plotly layout, `table_height()`, the sidebar's freshness note and Refresh button |
| `scripts/manage_logins.py` | Creates and resets manager logins |
| `.streamlit/config.toml` | Blue accent color per theme (see "Color" below) |

## The pages

| Page | Controls | Visuals | Reads |
|---|---|---|---|
| **Home** | — | standings with managers' real names; links to every page | `teams` |
| **Compare** | two teams (yours by default); season or one week | one-line verdict ("would beat X, winning 6…"); radar of category z-scores with a league-average ring; 3×3 small multiples of the raw values; table view | `v_team_week_cats` |
| **Power Rankings** | week slider (once there are 2+ weeks); injury assumptions | ranked table with all-play record, win %, category win %, rank movement (ties share a rank); projected finish through the end of the regular season, leaving injured players out of the weeks they're expected to miss, with a who's-missing list; rank-over-time chart with up to 3 highlighted teams | `v_power_rankings`, `v_all_play`, `v_player_pool`, `league_status` |
| **Matchups and Luck** | week picker | one scoreboard card per matchup (winner named, higher value bold); season-to-date luck bar chart; luck table | `v_luck`, `v_team_week_cats` |
| **Transactions** | dates, teams, actions, players (one filter bar for the chart and the log) | stacked activity per team with counts (adds, drops, trades, lineup moves); activity log of every matching row, lineup moves with their slots | `v_transactions` |
| **Roster Strength** | Category rankings tab: lens (roster strength / results), stat window, highlighted team (yours by default), sort. Per-game totals tab: stat window | rankings grid (rank per team × category plus average rank, the highlighted team outlined with Lock / Swing / Punt) and a category detail bar chart; per-game heatmap | `v_category_ranks`, `v_roster_strength` |
| **Trade Analyzer** | team (locked to yours unless admin), stat window, swing size δ, tier overrides | five tabs: Team profile; Waiver wire; Trade finder (win-win deals, top targets, trade chips); Create a Trade (search by player, or Offer Builder from your own trade block); Mock trade | `v_player_z`, `v_player_pool`, `v_player_profile` |
| **Player Rankings** | stat window; players (all, your team, free agents, any team); show ranks, per-game values or z-scores; name search; positions; hide injured | one table of every pool player: overall rank and rank in each of the 9 categories, shaded blue (1st) to red (last) like the team grid; team, position and health. Ranks are league-wide, so filters don't change them; columns sort; Player stays pinned when a phone swipes sideways | `v_player_z` |

### Choices made along the way

- **Compare's z-scores are computed in the app** (`compare.py`), not in a view: the
  period (one week, or the season) is a page control. Season mode uses per-week
  averages for counting stats and pools makes/attempts for percentages.
- **Compare's bars start at zero.** Two teams' FG% (.454 vs .463) look nearly equal
  as bars — honestly so. The radar is where differences show up, and every bar is
  labelled with its value.
- **Power rankings have no tiebreak.** Teams level on all-play win % share a rank.
- **The projected finish is always as of today**, whatever week the slider shows:
  finished weeks use actual all-play results, and every remaining week (the current
  one included) is projected from today's rosters, week by week as injured players
  return. It's Python (`app/analysis/projection.py`) rather than a view because the
  injury assumptions are adjustable on the page. Method: the Season projection
  section of [Step 5](step5-analytics.md) and the
  [Power Rankings doc](https://claude.ai/code/artifact/10b54502-9b3f-4312-b489-1ba7255b9b90).
- **Rank over time highlights 3 teams, not 14.** Fourteen colored lines can't be told
  apart; everyone else is a thin gray line.
- **The scoreboard's category score is ESPN's own** (from `v_luck`), so it always
  matches ESPN's matchup page.
- **Luck is season-to-date** through the chosen week — one week's luck is mostly noise.
- **Transactions shows every activity, lineup moves included**, filterable by every
  column; the log is sized to show every matching row.
- **Roster Strength's rankings use the app's blue-to-red scale** (rank 1 blue, last
  red), not green-to-red, to match every other chart and stay colorblind-safe.

## Trade Analyzer

The page recommends moves for one team — the signed-in manager's — ranked by how much
each raises its expected all-play category wins (E), and only suggests trades that
also help the other team. Method: *Category Rankings and the Trade & Waiver
Analyzer* in [proposal.md](proposal.md) and
[the explainer doc](https://claude.ai/code/artifact/86394802-b449-49d2-9d48-bc1a944873bb).
The math lives in `app/analysis/` and is tested on a synthetic 4-team league.

- **Team profile:** each category's rank, team z, gaps, weight and tier (Lock /
  Swing / Punt), plus E (out of 117) and the all-play matchup record. Tier overrides
  sit above the tabs and change every tab at once.
- **Waiver wire:** the top 10 add/drop pairs (free agents listed OUT skipped, IR
  players not dropped), each with a plain-text explanation.
- **Trade finder:** every 1-for-1 and 2-for-1 deal with every team, kept only if win-win.
  Rosters stay full: whoever gets two players drops their least useful, and whoever
  gives two picks up the best free agent. Lopsided deals (general value differs by
  more than 1.5 z) are hidden by default; deal sizes can be filtered. The full search
  takes about 0.6 seconds. Top targets and trade chips sit below.
- **Create a Trade:** two ways to build a deal, sharing the finder's scoring so a
  loaded deal matches the row's numbers:
  - *Search by player:* type a player on another roster; every 1-for-1, 2-for-1,
    1-for-2 and 2-for-2 that brings him over, labeled Likely to work / Costs you /
    They'd likely say no.
  - *Offer Builder* *(added later)*: pick your own trade block (up to 6 players,
    each noted if its value sits mostly in a Lock or Punt category) and a target
    team or "Any team," cap how many players either side gives, and choose an
    acceptance level — Win-win, Close call (costs the partner up to 2 E, not
    Lopsided) or Max gain (no limit, Lopsided deals flagged). Every deal up to
    3-for-3 is enumerated (a combinatorics guard refuses a search over 250,000
    deals before building any of it), balanced the same way the finder balances a
    2-for-1, and ranked by your gain. Each result expands into the usual plain-text
    "why it helps you," plus a **pitch** written from the partner's side of the same
    numbers — never a model, just the per-category deltas phrased the other way —
    and a **Load into mock trade** button. At most 3 offers per partner when
    searching every team, so one team can't fill the list.
- **Mock trade:** pick any players from both sides with dropdowns (or load any
  waiver, trade or offer row with **Load into mock trade** — dropdowns because
  Streamlit can't pre-select table rows from code). Beyond the trade itself, **Your
  other moves** lets you add any number of free agents and drop any number of your
  own players around it (the partner's own optional add/drop sit in a collapsed
  section, now also multi-select so an uneven Offer Builder deal can be fully
  represented); **Suggest a pickup** ranks free agents for the roster the move
  leaves you and adds one with a click; a **step-by-step** table shows E and
  matchup record at Now / Trade only / Trade + your moves. It also shows:
  - **Players in this deal:** each player's move, health (ESPN status and return
    date), average games played over the last 3 seasons and each season's count, and
    his 9 per-game categories; ESPN's season outlook for each in an expander
  - for each side: E and matchup record before and after, and per category the rank,
    tier, team z change and change in category wins — the same simulation the
    finder uses, so a loaded deal shows the row's numbers exactly
  - per-game roster totals before and after, ▲/▼ marked so direction never relies on
    color alone
- **An empty roster spot scores as a player with no stats**, not an average player,
  whenever a move changes roster size (a 2-for-1, an uneven Offer Builder deal, a
  plain pickup) — otherwise a 2-for-1 looked better than it was and every pickup
  into an open spot looked worthless.
- **IR players count for nothing** in team totals, the same rule as Roster Strength.

## Logins

Every page sits behind a manager login (`app/login.py`, `app/auth.py`). Each of the
14 managers has a username (`first.last`) and a random password; the commissioner
hands the passwords out.

- **Your team by default.** Once signed in, a manager's team is the default on
  Compare, Roster Strength and the Trade Analyzer. The Trade Analyzer is locked to
  it, so each manager gets waiver and trade recommendations for their own team. The
  commissioner's account (`eni.mosaku`) is an admin and can pick any team.
- **Creating and resetting logins:** `python scripts/manage_logins.py` reads the
  managers from BigQuery and gives anyone without a login a new one; `--reset
  first.last` issues a new password for one manager. Re-running keeps existing
  passwords and removes managers who've left the league.
- **What's stored where:** `.streamlit/secrets.toml` holds a random salt and the
  scrypt hash of each password, never the password (git-ignored; Streamlit reads it
  as `st.secrets`). The plain passwords from a run go to `manager-logins.csv`
  (git-ignored, owner-only) for the commissioner to send, then delete.
- **Lockout:** 5 wrong passwords for a username within 15 minutes lock it for the
  rest of that window, shared across all sessions so reloading doesn't reset it.
- **Stay signed in:** signing in stores a signed 30-day token in a cookie, so a
  reload (which phones do when you switch back to the browser) doesn't ask again.
  **Log out** in the sidebar clears it; resetting a password invalidates it.
- **On the live site** the same `secrets.toml` comes from Secret Manager
  (`dashboard-logins`); after changing logins, publish a new version — see
  [Step 7](step7-deploy.md).

## Implementation details that apply to every page

- **Caching:** every read goes through one `@st.cache_data(ttl=3600)` function in
  `queries.py`; the BigQuery client itself is an `@st.cache_resource`.
- **Freshness indicator and Refresh data:** the sidebar shows when ingest last wrote
  data (`MAX(ingested_at)` from `teams`), in Arizona time, with a **Refresh data**
  button that starts the `espn-ingest` Cloud Run Job (`app/refresh.py`), waits until
  the new data lands in BigQuery (about a minute), clears the query cache and
  reloads. It's disabled for 10 minutes after any update so the shared link can't
  hammer ESPN. On the live site, `dashboard-sa` may start that one job and nothing
  else.
- **Pre-season and empty states:** every page handles the league's current state —
  one week, all zeros — without errors: Compare says every team is level, Power
  Rankings explains the line chart appears after week 2, the results lens says it
  fills in after week 1, and window selectors only offer windows that have data.
- **Mobile-first:** columns stack on a phone; tables are sized to show every row;
  the Plotly toolbar is hidden.
- **9 categories, no turnovers:** every page takes its category list from
  `categories.py`.

### Color

Charts use the validated default data-viz palette, with separate steps for light and
dark mode (picked from Streamlit's active theme via `st.context.theme`):

- **Two-team and three-type charts** use the first three categorical colors (blue,
  orange, aqua) in fixed order — the three that stay distinguishable for colorblind
  viewers in every pairing. Colors follow the entity, not its position: on
  Transactions, Adds are always blue even when filtered; lineup moves are a quiet gray.
- **Above/below average and rankings** (luck, roster heatmap, category ranks) use a
  diverging blue ↔ red scale with a gray midpoint: blue is good, red is bad.
- **The app accent is blue**, not Streamlit's default red, so selected controls don't
  read as "bad". It's set per theme in `.streamlit/config.toml` — a top-level
  `primaryColor` would have pinned the whole app to light mode.

## Verification

- **Unit tests** — 67 in total across `tests/` (including `test_rankings.py`: league-wide ranks, shared ties, overall order). For the dashboard:
  - `test_math.py` (9): percentage pooling (1-for-1 plus 40-for-100 = 41/101, not
    70%), season averages, z-scores, head-to-head, per-game trade before/after
  - `test_analysis.py` (16): the spec's checks on a synthetic 4-team league — a
    runaway leader is Lock with D = 0, a hopeless trailer is Punt with U = 0, punting
    zeroes a weight and drops it from E, E sums to 9 × N(N−1)/2, a trade inside a
    punt category changes nothing, the finder only returns win-win deals — plus the
    mock trade reproducing every finder row, roster-filling, waiver rules, explanations
  - `test_projection.py` (7): injury defaults, ESPN return dates, adjustable rules,
    finished weeks using actual results, every projected week balancing
  - `test_auth.py` (11) and `test_refresh.py` (3): hashing, usernames, lockout and
    expiry, stay-signed-in tokens (forgery, expiry, password reset); the Refresh
    button's start-and-wait and timeout
- **Every page on live data** — run headlessly with Streamlit's `AppTest` against the
  real BigQuery views, signed in as a manager and as the admin: every page renders
  with no exceptions; a wrong password is refused; a manager is locked to his team;
  loading the top trade into Mock trade shows the row's ΔE exactly (+14 / +1).
- **Live checks of the analysis:** the analyzer's team totals match
  `v_team_category_z` exactly; the trade search for team 10 takes 0.6 seconds; the
  Refresh button ran the real ingest job in 47 seconds.
- **Every page on a realistic season** — live data is still all ties, so the app was
  also run with a synthetic 4-week season patched in from outside the repo, and
  screenshotted in a real browser at desktop and phone width, light and dark mode.
  That caught: the radar's white background in dark mode, a trailing space breaking
  bold team names, tables cut at 10 of 14 rows, an accent color forcing light mode,
  and "would win 0-9-0" for a team that loses every category.

## Done when

All pages run locally against BigQuery with `streamlit run app/Home.py`, behind
logins, with real data on every page. **Done.** The remaining check needs real
games: once Week 1 has numbers, open Matchups and Luck and compare one scoreboard to
ESPN's matchup page.
