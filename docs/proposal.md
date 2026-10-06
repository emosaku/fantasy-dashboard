# ESPN Fantasy Basketball Dashboard on GCP — Build Plan

This is the living Markdown version of the original build proposal PDF, kept in
version control so the plan can evolve with the project rather than staying frozen as
a static document. Where this diverges from the original PDF, it's marked explicitly
*(added after the original proposal)*: **Mock Trade Analysis**, **Category Rankings
and the Trade & Waiver Analyzer**, and the **later additions** (manager logins, an
injury-aware season projection, the full activity log, an on-demand refresh, and
player health and games-played history) — each with its own section below.

## Overview and goals

Build a hosted dashboard for a private ESPN fantasy basketball league, fed by a
scheduled pipeline on Google Cloud, in roughly 30–40 hours across 7 steps. The league
gets one link; data refreshes automatically; every view is backed by BigQuery history
ESPN itself doesn't keep.

The dashboard ships six features:

- **Category comparison** — any two teams side by side across the league's scoring
  categories (radar and bar charts)
- **Category power rankings** — teams ranked by category wins each week, not just
  W/L
- **Matchup breakdowns and luck analysis** — weekly results plus each team's record
  if it had played everyone
- **Trade and waiver tracking** — a running log of adds, drops, and trades
- **Roster strength by category** — where each roster is stacked or thin
- **Mock trade analysis** *(added after the original proposal)* — model the category
  impact of a hypothetical trade between two teams before proposing it for real
- **Category rankings and a trade & waiver analyzer** *(added)* — every team ranked
  in every category, and waiver pickups and win-win trades recommended per team
- **Manager logins, a projected finish, the full activity log, on-demand refresh**
  *(added)* — see "Later additions" below

The original plan assumed the standard 9 categories with turnovers. The real league
(confirmed in Step 2) is 14 teams, head-to-head **Most Categories**, scoring FG%, FT%,
3PM, **3PT%**, REB, AST, STL, BLK, PTS — no turnovers — over a 16-week regular season.
Everything built follows the real league.

## Architecture

Six GCP services plus GitHub: a scheduled job writes, BigQuery stores, and a Cloud
Run app reads.

```
Cloud Scheduler (daily 5:00 AM AZ trigger)
        │
        ▼
Cloud Run Job: espn-ingest  ──reads cookies──  Secret Manager (espn_s2, SWID)
        │
        │  pulls league data via the unofficial ESPN Fantasy API (espn-api)
        │  MERGEs into BigQuery
        ▼
BigQuery: fantasy dataset (raw tables + analytics views; 9 and 12 as built)
        │
        ▼
Cloud Run: Streamlit app (cached queries, manager logins)
        │
        ▼
League managers (one link, any device, each with a login)
```

GitHub Actions deploys both Cloud Run services on push to `main`. Credentials never
leave the ingest side; the dashboard's service account reads BigQuery and (for the
Refresh data button) may start the ingest job, which still runs as `ingest-sa`.

## Step 1: Prerequisites (about 2 hours)

Set up the GCP project and grab the two ESPN cookies a private league needs.

1. Create a GCP project (e.g. `fantasy-hoops-dash`) and attach billing. Set a budget
   alert at $5/month so nothing surprises you.
2. Enable the APIs: Cloud Run, Cloud Scheduler, BigQuery, Secret Manager, Artifact
   Registry, Cloud Build.
3. Install the `gcloud` CLI locally and run `gcloud auth application-default login`
   so local code can reach BigQuery.
4. Create two service accounts with least-privilege roles:
   - `ingest-sa`: BigQuery Data Editor, BigQuery Job User, Secret Manager Secret
     Accessor
   - `dashboard-sa`: BigQuery Data Viewer, BigQuery Job User
5. Get your league ID from the ESPN league URL (`leagueId=` in the address bar).
6. Get the private-league cookies: log in to ESPN Fantasy in a desktop browser, open
   DevTools → Application → Cookies → `espn.com`, and copy `espn_s2` and `SWID`
   (keep the curly braces on `SWID`).
7. Create a GitHub repo with this layout:

   ```
   fantasy-dash/
     ingest/        # Cloud Run Job: ESPN → BigQuery
     sql/            # table DDL and analytics views
     app/             # Streamlit dashboard
     .github/workflows/
   ```

Treat the cookies like a password: they grant access to your ESPN account. Never
commit them; they go straight into Secret Manager in Step 4.

## Step 2: Local data access (about 3 hours)

Prove you can pull every dataset the six features need before touching the cloud.

```python
# pip install espn-api pandas
import os
from espn_api.basketball import League

league = League(
    league_id=int(os.environ["LEAGUE_ID"]),
    year=2027,  # ESPN labels the 2026-27 season by its ending year
    espn_s2=os.environ["ESPN_S2"],
    swid=os.environ["SWID"],
)

for team in league.teams:
    print(team.team_id, team.team_name, team.wins, team.losses)

box_scores = league.box_scores(matchup_period=1)  # per-category results
activity = league.recent_activity(size=50)          # adds, drops, trades
```

What each feature pulls:

| Feature | espn-api source |
|---|---|
| Category comparison | `league.box_scores()` category stats per team per matchup |
| Power rankings | `league.box_scores()` for every matchup period so far |
| Matchups and luck | `league.box_scores()` + `league.teams` |
| Trades and waivers | `league.recent_activity()` |
| Roster strength | `team.roster` and each player's `stats` |
| Mock trade analysis *(added)* | `team.roster` and each player's `stats` — same source as roster strength, no new pull |

**Done when:** a notebook prints a pandas DataFrame for each row above. Field names
shift between library versions, so inspect objects with `vars()` rather than
trusting docs.

## Step 3: BigQuery data model (about 3 hours)

One dataset, `fantasy`, with five raw tables; every row carries `season` and
`ingested_at` so history accumulates.

| Table | Grain | Key columns | Partition / cluster |
|---|---|---|---|
| `teams` | team × snapshot date | `team_id`, `team_name`, `owner`, `wins`, `losses`, `ties`, `standing` | partition `snapshot_date` |
| `matchup_categories` | matchup period × team × category | `matchup_period`, `team_id`, `opponent_id`, `category`, `value`, `result` (W/L/T) | cluster `matchup_period`, `team_id` |
| `rosters` | snapshot date × team × player | `team_id`, `player_id`, `player_name`, `position`, `lineup_slot`, `injury_status` | partition `snapshot_date` |
| `player_stats` | snapshot date × player × stat window | `player_id`, `window` (season, last 7, last 15, last 30), PTS, REB, AST, STL, BLK, 3PM, FGM, FGA, FTM, FTA, TO | partition `snapshot_date` |
| `transactions` | one row per action | `txn_id`, `txn_date`, `team_id`, `action` (ADD, DROP, TRADE), `player_id`, `player_name` | partition `txn_date` |

Two design choices matter:

- **Store makes and attempts, never just percentages.** FG% and FT% must be
  recomputed as `SUM(FGM) / SUM(FGA)`; averaging percentages gives wrong answers.
- **Long format for categories** (one row per category) keeps SQL views generic, so
  adding a 10th category is a config change, not a schema change.

Keep the DDL in `sql/ddl/` so the schema lives in version control.

No new tables for mock trade analysis — see the feature design below, which reuses
`rosters` and `player_stats` as-is. Later features added four tables (`free_agents`,
`league_status`, `player_seasons`, `player_details`) and a few columns; see
[step4-ingest.md](step4-ingest.md).

## Step 4: Ingest job (about 6 hours)

A containerized Python script runs as a Cloud Run Job, reads cookies from Secret
Manager, and loads all five tables into BigQuery on a schedule.

1. Store the cookies:

   ```bash
   printf '%s' "$ESPN_S2" | gcloud secrets create espn-s2 --data-file=-
   printf '%s' "$SWID"    | gcloud secrets create espn-swid --data-file=-
   ```

2. Write `ingest/main.py`: build the `League` object, transform each source into a
   DataFrame, and load with `google-cloud-bigquery`.
3. Make every load idempotent. Load into a staging table, then `MERGE` into the
   target on its natural key (e.g. `matchup_period + team_id + category`). Re-runs
   then never duplicate rows.
4. Containerize with a slim `python:3.12-slim` Dockerfile and deploy:

   ```bash
   gcloud run jobs deploy espn-ingest \
     --source ingest/ --region us-west1 \
     --service-account ingest-sa@PROJECT.iam.gserviceaccount.com \
     --set-secrets ESPN_S2=espn-s2:latest,SWID=espn-swid:latest \
     --set-env-vars LEAGUE_ID=12345,SEASON=2027
   ```

5. Schedule it with Cloud Scheduler: daily at 5:00 AM Arizona time (after the
   night's games settle), plus an optional extra run Monday morning when matchups
   close.
6. Fail loudly: if ESPN returns a 401, the cookies expired. Log a clear error and
   set up a Cloud Monitoring alert on job failures so you know to refresh the
   secret.

**Done when:** a manual `gcloud run jobs execute espn-ingest` fills all five tables,
and running it twice changes no row counts.

## Step 5: Analytics layer (about 6 hours, +~1 hour for mock trade analysis)

Put all the logic in BigQuery views so the dashboard only selects and plots.

The core of all-play, in SQL:

| View | Feature | Logic |
|---|---|---|
| `v_team_week_cats` | Category comparison | Pivot `matchup_categories` to one row per team-week with the 9 scoring categories; recompute FG%, FT% and 3PT% from makes and attempts |
| `v_all_play` | Power rankings, luck | Self-join every team to every other team in the same week; decide each simulated matchup on category wins, then roll up to an all-play record per team-week |
| `v_power_rankings` | Power rankings | Season totals from `v_all_play`: all-play win %, category win %, rank |
| `v_luck` | Luck analysis | Actual win % minus all-play win %; positive means lucky |
| `v_transactions` | Trade and waiver tracking | Latest transactions with team names joined; counts per team |
| `v_roster_strength` | Roster strength | Sum each roster's per-game player stats (last 15 days); z-score each category across the league |
| `v_team_roster_stats` *(added)* | Mock trade analysis | Current roster joined to each player's per-game stat line (raw per-game averages, **not** z-scored — see below for why) |

```sql
-- one row per simulated head-to-head, over the 9 scoring categories
SELECT a.matchup_period, a.team_id, b.team_id AS opponent_id,
       COUNTIF(a.value > b.value) AS cat_wins,
       COUNTIF(a.value < b.value) AS cat_losses
FROM cats a   -- v_team_week_cats unpivoted to long format
JOIN cats b
  ON a.matchup_period = b.matchup_period
 AND a.category = b.category
 AND a.team_id != b.team_id
GROUP BY 1, 2, 3
```

Each pairing is then a W, L or T on category count, and those roll up into the team's
weekly all-play record. The league scores 9 categories (FG%, FT%, 3PM, 3PT%, REB, AST,
STL, BLK, PTS); higher wins in all of them, and there's no turnovers category. The
attempt-only rows (FGM, FGA, FTM, FTA, 3PA) are never compared directly; they only
feed the recomputed percentages in `v_team_week_cats`. Test every view against a week you
can verify by hand on ESPN.

**Why `v_team_roster_stats` isn't z-scored like `v_roster_strength`:** z-scores are
league-relative (how this roster compares to every other roster), which is the right
lens for "where is my team stacked or thin." A trade's impact is a before/after
comparison of two specific rosters' own raw totals — z-scoring would make "gained 3
rebounds a night" unreadable. Mock trade analysis needs the plain per-game numbers,
so it gets its own lightweight view rather than reusing `v_roster_strength` directly.

## Step 6: Streamlit dashboard (about 10 hours, +~5 hours for mock trade analysis)

A multipage Streamlit app with one page per feature, using Plotly for charts and
cached BigQuery reads.

Key implementation details:

- Wrap every query in `@st.cache_data(ttl=3600)` so page clicks don't rerun BigQuery
  queries. Data only changes once a day anyway.

| Page | Controls | Visuals |
|---|---|---|
| Compare | Pick two teams, week or season (Players mode *(added)*: 2-4 players, any stat window) | Radar chart of category z-scores; side-by-side bars per category |
| Power Rankings | Week slider | Ranked table with all-play record; rank-over-time line chart |
| Matchups and Luck | Week picker | Category scoreboard per matchup; luck bar chart (actual vs all-play win %) |
| Transactions | Team filter, action filter | Activity log table; adds and drops per team bar chart |
| Roster Strength | Stat window (7, 15, 30 days) | Team × category heatmap of z-scores |
| Trade Analyzer *(added)* | Two team pickers, two player pickers | Before/after/delta category table, both sides — see feature design below |

- Keep one `queries.py` module that maps each page to its view; pages never contain
  raw SQL.
- Show a "last updated" timestamp from `MAX(ingested_at)` in the sidebar so the
  league trusts the numbers.
- Use the `st.navigation` pages API for the multipage layout and test on a phone,
  since most of the league will open it there.

**Done when:** all six pages run locally against BigQuery with
`streamlit run app/Home.py`.

### Feature design: Mock Trade Analysis *(added after the original proposal)*

**Goal:** model the category impact of a hypothetical trade between two teams,
before proposing it for real.

**UI flow:**

1. Two team pickers at the top of the page: **"Your team"** and **"Trade
   partner"** — both populated from `teams`; the trade-partner list excludes
   whichever team is picked as "yours."
2. Once both teams are chosen, two player pickers appear, one per team, each
   listing that team's current roster (from `v_team_roster_stats`) with every
   player's per-game stat line shown alongside their name — so you can see what
   you're trading without leaving the picker.
3. **Clicking a player's name moves them into the "selected to trade" section
   below** rather than just highlighting a dropdown row — selection is the action,
   not a separate "add" button. Clicking a selected player's name again removes
   them (toggle on/off).
4. Below the pickers, a section with two mirrored halves — **your side** and
   **your trade partner's side** — each showing:
   - the players that side is sending away (selected from their own roster)
   - the players that side is receiving (selected from the other roster)
   - that roster's category totals and per-game averages **before** the trade,
     **after** the trade, and the **delta** (gained or lost) per category

**Data needed:** no new ingest source and no new raw table — `rosters` and
`player_stats` (Step 3) already carry everything this needs. The one addition is
`v_team_roster_stats` (Step 5), a join of current roster to per-game stats, so the
app has one clean, already-joined source instead of assembling it from two raw
tables in Python every time a selection changes.

**Where the logic lives, and why this is the one exception to "logic belongs in
SQL":** every other page in this dashboard reads a precomputed view and just plots
it. Trade analysis can't work that way — which players are "sent" and "received" is
arbitrary and changes on every click, so there's nothing fixed to precompute. The
view supplies each roster's current player-level stats once; the
before/after/delta arithmetic (sum the selected players in, sum the selected
players out, recompute each roster's totals and averages) happens in the Streamlit
app itself, recalculated live as the selection changes. This is a deliberate,
named departure from the rest of the app's architecture, not an oversight.

**"Your team" comes from the login** *(changed after manager logins were added)*:
the original design had no login, so "your team" was whichever team you picked. Now
each manager signs in, their team is the default, and the Trade Analyzer is locked
to it (the commissioner can pick any team). As built, players are picked with
dropdowns and every waiver or trade recommendation can be loaded into the mock trade.

### Feature design: Category Rankings and the Trade & Waiver Analyzer *(added after the original proposal)*

Two features built on one shared foundation: every player's z-score in each of the
9 categories. They extend Roster Strength and the Mock Trade Analysis above rather
than replacing them.

**Foundation.** The player pool is every rostered player plus the top 100 free
agents ESPN lists that day (a new `free_agents` table, with their stat lines in
`player_stats`). Counting categories use `(x - mean) / sd` of per-game averages.
FG%, FT% and 3PT% are volume-weighted: `impact = (player % - league %) x attempts`,
then z of impact. A **Blended** window mixes season and projected z by games played,
`alpha = min(GP / 20, 1)` (a new `player_stats.gp` column). A team's strength in a
category is the sum of its non-IR players' z. Views: `v_player_pool`, `v_player_z`,
`v_team_category_z`, `v_category_ranks`.

**Category Rankings** (a tab on the Roster Strength page): every team ranked 1-14 in
every category plus an average rank, in two lenses -- *Roster strength* (team z
totals per stat window; works before games start) and *Results* (finished weeks:
average weekly totals, percentages from total makes over attempts, plus an
all-play win rate per category; empty until week 1 finishes). The highlighted team
(the signed-in manager's team by default) is outlined and shows its tiers; a category detail chart shows
the gaps that ranks hide.

**Trade & Waiver Analyzer** (the Trade Analyzer page), five tabs:

- *Team profile:* rank, team z, gaps, weight and tier per category, plus the team's
  E and all-play matchup record.
- *Waiver wire:* every add/drop pair, ranked by change in E.
- *Trade finder:* every 1-for-1 and 2-for-1 deal with every team, keeping only
  win-win deals (my E up, theirs not down), with a Lopsided flag (general value
  given vs received differs by more than 1.5 z, hidden by default), top targets and
  trade chips.
- *Create a Trade:* two ways to start a deal -- search by one player you want
  (every 1-for-1/2-for-1/1-for-2/2-for-2 that brings him over, sorted by how likely
  the other manager is to accept), or **Offer Builder** *(added later)*: pick your
  own trade block (up to 6 players) and a target team or "Any team," and every deal
  up to 3-for-3 built from it comes back ranked Win-win / Close call / Max gain,
  each with a pitch written from the partner's side of the numbers.
- *Mock trade:* the simulator above, now with ranks, tiers, E and record before and
  after for both teams, your own adds/drops around the trade, a step-by-step E
  breakdown and a free-agent pickup suggestion; any recommendation loads into it
  with matching numbers.

Key definitions: a category's **weight** for a team is how many opponents a change
of delta (default 1.0 z) would flip, `(U + 0.5 D) / (N - 1)`, scaled to average 1.
**Tiers:** Lock = top 3 with nobody within delta behind; Punt = bottom 3 with nobody
within delta ahead (weight 0); Swing = the rest; the user can override any of them
for the session. **E** = categories won against every other team (ties half,
punted categories excluded), max 9 x 13 = 117. Every recommendation is verified by
recomputing team totals with the move applied, and explained in plain text counted
from the per-category change ("+2 category wins: passes 2 teams in BLK, 1 in FG%;
costs 1 team in 3PM").

Adapted to this league: it scores 3PT% rather than turnovers, so no category needs a
sign flip; it has 14 teams, not 12. One rule added beyond the original spec: in a
2-for-1, the side left a player short picks up the best available free agent for
the open spot, so both rosters stay full and 2-for-1s aren't a free upgrade for
whoever receives two players. The math lives in a tested package, `app/analysis/`.

### Feature design: Player Compare *(added after the original proposal)*

A **Teams | Players** toggle on the Compare page. Teams mode is the original page
above, unchanged. Players mode compares 2-4 players (rostered or free agent) on the
same z-score foundation as Player Rankings and the Trade Analyzer, so a player's
rank and value always match what those pages show.

- **Picker:** searchable multi-select (every pool player, labelled with position,
  team or FA, and a health badge), filter chips (My team / Other teams / Free
  agents), a stat window selector. Player Rankings ("Compare selected", after
  selecting 2-4 table rows) and every Trade Analyzer recommendation row ("Compare
  players") can open this page pre-loaded, via `st.session_state["compare-players"]`
  (clipped to 4 — an uneven Offer Builder deal can touch up to 6 players).
- **Category radar**, clipped to ±3 SD so one outlier doesn't flatten it (true value
  on hover); grouped horizontal bars instead on a narrow screen (a `Sec-Ch-Ua-Mobile`
  client hint picks the default; a toggle overrides it either way).
- **Stat table:** one row per category, one column per player — per-game value,
  league rank, makes/attempts beside a percentage (e.g. "48.2% on 15.1 FGA" — volume
  is what moves a team's percentage); the best value in each row is bold; footer
  rows for overall rank, total z and games played.
- **Fit for your team:** each player's value to the signed-in manager's team
  (`v = Σ weight × z`, the same number the Trade Analyzer shows) next to his generic
  total z, and the tier breakdown in words ("70% of his value is in your Swing
  categories") — two players who rank similarly overall can look very different here.
- **Recent form:** total z across Last 7/15/30 and Season as a small line chart, so
  trending up or down shows without a separate page.
- **Health and durability:** the same component (and the same `queries.player_profile()`
  read) the Mock trade's "Players in this deal" table already uses, factored out to
  `app/health.py` so both share it.
- With exactly 2 players, a one-line verdict ("Player A wins 6 of 9 categories;
  Player B is better in FT%, 3PT% and STL"), counted by z (not the raw percentage,
  so volume is judged the same way as everywhere else on the page).
- **Per game / Season totals** toggle *(added)*: totals are per-game stats times
  games played in the stat window (projected games for Projected), so a 70-game
  player counts for more than a 40-game one. Percentages come from season makes and
  attempts; totals are ranked among every pool player's totals, and the verdict and
  bolding switch to totals too. The charts and the fit row stay per game.
- **Position baseline** *(added)*: "Compare against: average starting PG/SG/SF/PF/C"
  -- the mean of every rostered player at that position in an active lineup slot
  (not bench or IR; 17-31 per position in this league). It's a full row everywhere
  (chart, table with the rank its z would hold, fit, form, a durability average)
  drawn in neutral gray, so one player can be measured against a typical starter.

A fourth categorical color (`ui.py`'s `series` palette only defines 3) was added for
the 4-player case, paired with a distinct line/marker style per player so identity
never rests on color alone. Every Teams-mode widget needed converting from
`index=`/`default=` to a session-state-first pattern: Streamlit clears a
selectbox/segmented_control/pills widget's state for any run where its branch
doesn't execute (confirmed empirically; `st.multiselect` isn't affected), which a
plain Teams ↔ Players toggle hits on every switch. The math lives in `compare.py`
(`player_compare_frame`, `head_to_head_verdict`) and `app/analysis/weights.py`
(`player_fit`), both tested on a synthetic pool.

### Later additions *(added after the original proposal)*

- **Manager logins.** Every page sits behind a login; each of the 14 managers has a
  username and a random password from `scripts/manage_logins.py`. Only salted scrypt
  hashes are stored (`.streamlit/secrets.toml`, git-ignored); 5 wrong passwords lock
  a username for 15 minutes. A manager's team is the default everywhere and the
  Trade Analyzer is locked to it, so everyone gets recommendations for their own team.
  A signed 30-day cookie keeps managers signed in across reloads (phones reload
  often).
- **Projected finish** on Power Rankings: actual all-play results for finished weeks
  plus each remaining week projected from today's rosters, leaving injured players
  out of the weeks they're expected to miss (ESPN's return date, else 4 weeks for
  IR, 2 for Out, 1 for day-to-day — all adjustable). Python, not a view, because the
  assumptions change on the page (`app/analysis/projection.py`).
- **Full activity log.** Ingest reads every page of ESPN's activity feed, lineup
  moves included, with player ids; the Transactions page filters on every column.
- **Refresh data** button: runs the ingest job on demand alongside the daily
  schedule, with a 10-minute cooldown.
- **Player health and durability.** Ingest stores ESPN's injury status, return date
  and season outlook, and games played in each of the last 3 seasons; the mock trade
  shows them for every player in the deal.
- **Managers' real names** instead of ESPN usernames.
- **Player Rankings** page: every player ranked in each category and overall,
  league-wide, shaded like the team rankings, with team/position/health filters.

## Step 7: Deploy and share (about 4 hours)

Deploy the Streamlit app as a Cloud Run service and give the league one URL.

```bash
gcloud run deploy fantasy-dash \
  --source app/ --region us-west1 \
  --service-account dashboard-sa@PROJECT.iam.gserviceaccount.com \
  --allow-unauthenticated --min-instances 0 --max-instances 2 \
  --session-affinity
```

- The Dockerfile runs `streamlit run Home.py --server.port=$PORT
  --server.address=0.0.0.0`. Cloud Run supports the websockets Streamlit uses;
  session affinity keeps each viewer on one instance.
- **Access:** `--allow-unauthenticated` lets the link reach the app; the app itself
  requires a manager login on every page. The login hashes (`secrets.toml`) go in
  Secret Manager and are mounted into the service. The dashboard holds no ESPN
  credentials.
- **Refresh button:** `dashboard-sa` needs `roles/run.invoker` on the `espn-ingest`
  job (and only that job).
- **CI/CD:** a GitHub Actions workflow authenticates with Workload Identity
  Federation (no JSON keys) and redeploys the app on pushes to `main` that touch
  `app/`, and the job on pushes that touch `ingest/`.
- **Custom URL (optional):** map a domain you own with Cloud Run domain mapping or
  a load balancer.

**Done when:** someone in the league opens the link on their phone and sees today's
data. **Done** — live on Cloud Run as `fantasy-dash`; see
[step7-deploy.md](step7-deploy.md) for exactly what was built.

## Timeline, cost, and risks

At about 8 hours a week, the original 7 steps ship in 4–5 weeks; costs should stay
under $1/month, inside GCP free tiers. Mock trade analysis adds roughly 6 hours on
top of that (≈1 hour in Step 5, ≈5 hours in Step 6, mostly the interactive
add/remove-and-recompute logic) — call it 4–6 weeks at the same pace.

**Cost:** BigQuery stores well under 1 GB and queries far under the 1 TB/month free
tier. Cloud Run, Scheduler (3 free jobs), and Secret Manager all fit their free
tiers at league scale. The budget alert from Step 1 is the backstop.

| Risk | Impact | Mitigation |
|---|---|---|
| ESPN cookies expire | Ingest fails with 401 | Failure alert; add a new secret version, no redeploy needed |
| ESPN changes its unofficial API | Ingest breaks | Pin the `espn-api` version; raw tables keep history even if a run fails |
| Library fields differ by version | Wrong or missing columns | Validate DataFrame columns before loading; fail the run on mismatch |
| Percentage categories miscomputed | Wrong rankings | Store makes and attempts; recompute in SQL |
| Cold starts | First page load takes a few seconds | Accept it, or set min instances to 1 (adds cost) |

## Stretch goals

Once the core ships (now including mock trade analysis, promoted out of this list):
a dbt project for the views, playoff odds via Monte Carlo simulation (the projected
finish is a deterministic first step toward it), and a weekly recap posted to the
league's group chat.
