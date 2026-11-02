# UI rebuild plan: Streamlit → custom React frontend

**Branch `ReactFrontend`, cut from `WhopVersion` (November 1, 2026).** Read
[../whopDocs/moat.md](../whopDocs/moat.md) first: it defines what makes this product
defensible and the hard constraints on any change. This document defines what to
build, why, and how.

Original draft written with Meta Muse; this copy is updated to match the current
codebase. Every change from the draft is listed in
[Updates from the original draft](#updates-from-the-original-draft) at the end.

## 1. Goal

Rebuild League Lab's frontend as a custom React app so the product sells as a hosted
service on Whop. The Streamlit app works but looks like Streamlit; the rebuild must
look like a modern sports product (references below) while keeping every existing
capability, for both categories and points leagues.

**Non-goal:** rewriting the data pipeline or the analysis math. The ingest jobs
(`league-ingest`, `nba-nightly`), the BigQuery history and the analysis modules
(`app/analysis/`, `app/points/`) are the product's engine and moat. They stay in
Python, untouched except where the API layer needs it.

## 2. Hard constraints (do not violate)

- **The daily refresh never stops and never breaks history.** Re-running stays safe
  (idempotent replace by scope), table contracts stay as they are, and the snapshot
  tables (`snap_*`, `nba_injury_history`) are preserved. The history is the moat.
- **The analysis code stays pure Python.** The trade, waiver, projection and points
  math is tested (322 tests across the repo). It is never reimplemented in JavaScript:
  the React app calls it through the API and never duplicates it.
- **The browser never touches BigQuery.** All data flows through the FastAPI layer. No
  service-account keys in frontend code, no direct BigQuery queries.
- **Secrets stay secret.** ESPN `espn_s2`/`SWID` cookies, API keys, sign-in secrets
  and tokens are never committed, logged or printed.
- **Moat features don't get watered down** (moat.md: league history, the proactive
  win-win trade finder, luck analysis, Lock / Swing / Punt tiers). If a UI change makes
  one behave like a generic competitor's version, flag it.

## 3. Reference library (what to take from each)

| Reference | Take this |
|---|---|
| Roster Rebel (rosterrebel.com) onboarding | Stepped wizard for ESPN registration: progress bar, one question per screen, Public league (paste URL, RECOMMENDED) / Private league / Manual fallback. Plain-language explanations, "we never see your ESPN password", "not affiliated with ESPN" disclaimers |
| League Winner (leaguewinnersports.com) landing page | Ad style: proof-number headline, verb-first benefit sections ("Start winning trades"), real product screenshots inline, daily content as SEO |
| League Winner /weekly-slate header | Header nav with dropdown menus that deep-link to page sections |
| HoopsIQ (app.fantasyhoopsiq.com) | Layered card UI: list → card → click → slide-over detail panel. "Show your work" explainers in plain language. "You give" / "You get" two-panel trade layout with a swap button, dashed add-player zones, league-context settings, verdict section. Player headshots. Dark theme |
| Sleeper app | Mobile bottom tab bar (5 icons). Card-based mobile layouts |
| Basketball-Reference | The stat-table standard: sortable columns, subtle shading, per-game / totals toggles |
| Milo-Coolman/Fantasy-Basketball-Optimizer (GitHub) | Proof that this stack (ESPN league data + z-scores + trade analyzer) works with a React frontend; the closest structural comparison |

**Key product insight:** HoopsIQ optimizes one roster in a vacuum. It can't find
win-win trades, because that takes modeling every roster in the league. Our
whole-league modeling is the difference, and the landing-page line is: **"We model
your entire league, not just your team."**

## 4. Information architecture: 5 pages

Today's Streamlit app has 7 categories pages and 6 points pages, plus Home, Register,
League admin and Privacy. They consolidate into 5 destinations, each with a
categories and a points version of its sections where the math differs.

**Why:** 5 items fit a header nav and a mobile bottom tab bar; 9 don't. Fewer
destinations mean easier onboarding and less support, and related analyses live
together and cross-link.

| Page | Sections | From today's pages |
|---|---|---|
| Overview | Standings · Power Rankings · Luck snapshot · Projected finish | Home, Power Rankings |
| Matchups | This week · All-play & luck · Team compare | Matchups & Luck, Compare (teams) |
| Players | Roster strength · Player rankings · Waiver wire | Roster Strength, Player Rankings, Compare (players) |
| Trades | Trade finder · Mock trade · Create a trade · Team profile · Saved trades | Trade Analyzer |
| Activity | Transactions (filterable log) | Transactions |

League admin, Register and Privacy move to the avatar menu and the onboarding flow.

**Dropdown deep links** (instead of an everything-drawer): each header item has a
hover dropdown (on mobile, an accordion in the hamburger menu) listing its sections.
Each links to a route and anchor (e.g. `/trades#finder`); the page loads scrolled to
that section with a brief highlight. That keeps one-click access to about 15
destinations from a 5-item bar, and gives shareable URLs: a "check this trade" link
pasted in the league chat is a growth loop, not just navigation.

**Migration note:** the Trade Analyzer's six tabs (Team profile, Waiver wire, Trade
finder, Create a trade, Mock trade, Saved trades) become the Trades page's sections;
Waiver wire moves to Players. A relocation, not a reorganization.

## 5. Global chrome

**Desktop header** (HoopsIQ's anatomy):

```
[Logo] Overview | Matchups | Players | Trades | Activity     [League ▾] [⟳ Updated 5:30 AM] [Avatar ▾]
```

- Sticky top bar; the active item underlined; dropdowns on hover (section 4).
- **League switcher:** a user can already have several leagues, each locked to
  categories or points; switching changes which version of each section shows.
- **Data-freshness pill** with manual refresh: it builds trust in the daily refresh.
- **Avatar menu** replaces the sidebar's "Signed in as ..." and sign-out block, and
  holds League admin, Privacy and the subscription.

**Mobile:** bottom tab bar with 5 icons (Sleeper pattern); the hamburger menu holds
the dropdown section lists as accordions.

**Onboarding wizard** (a new user registers a league, Roster Rebel pattern):

- **Step 1, "How should we get your team?":** three cards:
  - **Public league** (RECOMMENDED): "paste your ESPN league link, we read it for
    you, updates every morning".
  - **Private league:** "connect with your ESPN login". Hidden at launch: public
    leagues only (Whop backlog R15).
  - **Set up by hand:** "no automatic updates". Doesn't exist today; a later
    decision.
- **Why it matters technically:** public ESPN leagues need no credentials; the
  ingest reads them without `espn_s2`/`SWID`. The public path removes the biggest
  onboarding friction, and only private leagues need a login.
- Then the steps today's Register page already does: check the league, show its
  format (categories or points, locked for the season), its categories or point
  values, any scored stats we can't count, and pick your team.
- Segmented progress bar, one question per screen, back navigation, plain-language
  copy, and "not affiliated with ESPN" on every step.

## 6. Page-by-page build spec

### 6.1 Overview

**What:** standings, power rankings, luck snapshot and projected finish on one screen.

**Why:** the first impression; it answers "how is my league doing" in 10 seconds.

**How:** standings table (Basketball-Reference conventions); power rankings as ranked
cards with the all-play record beside the actual record (the luck story told
visually); projected finish as a small chart or ordered list.

### 6.2 Matchups

**What:** weekly scoreboards, all-play and luck detail, team-vs-team compare.

**Why:** luck analysis is a moat feature; it deserves a full page, not a tab.

**How:** a week pager at the top; matchup cards that expand to category-by-category
scoreboards (categories) or player-by-player points (points); a Luck section with
actual vs expected wins and a plain-language explainer; compare mode as two team
pickers rendering side-by-side category bars or weekly points.

### 6.3 Players

**What:** the Roster Strength heatmap, the Player Rankings heatmap and the Waiver
wire.

**Why:** both heatmaps cover the same player pool; keeping them together invites
comparison.

**How, for both grids:**

- **Tier pills, not suffixes.** Replace cryptic "8 S" cell text with colored Lock /
  Swing / Punt pills and an inline legend. Today's paragraph-long legend shows users
  need this.
- **Week-over-week change (▲2 / ▼3).** Uses the history moat; nobody else can show it.
  High priority. The daily snapshots (`snap_category_ranks`, `snap_player_z`,
  `snap_player_points`) now exist, so this is a read of data already being kept.
- Sortable column headers, not just a dropdown.
- The user's team row pinned and highlighted, with a "my team" toggle.
- Hover tooltips with the underlying values (the actual category numbers, not only
  ranks).
- **Player headshots** from the NBA's image CDN
  (`cdn.nba.com/headshots/nba/latest/260x190/{nba_id}.png`). Needs an ESPN → NBA.com
  player id table; Wikidata's NBA.com id (P3647) is already in our matching data.
  **Ask the lawyer first:** NBA headshots are the NBA's images, and showing them in a
  paid product is a rights question (add to legal-questions.md).
- Tier divider lines at z-score cliffs; a blue/orange diverging scale (colorblind-safe;
  today's blue/red isn't).
- Sticky header row and first column; horizontal scroll on mobile.
- Checkboxes become an explicit "Select 2 → Compare" action that links to
  `/matchups#compare` or the player compare.
- Long explainer text becomes an info tooltip; the "blue = top" convention is
  documented once.

### 6.4 Trades (the money page: polish hardest)

**What:** Trade finder (proactive win-win), Mock trade, Create a trade, Team profile,
Saved trades.

**Why:** the proactive trade finder is moat feature 2 and the main reason to
subscribe. The page must feel verdict-first, not like a form.

**How** (HoopsIQ's trade layout):

- **Mock / create:** "You give" (warm accent) and "You get" (cool accent) panels with a
  swap button between; dashed "add player" drop zones; player rows show headshot,
  team, positions, the key number (category value or fantasy points per game) and an
  injury badge.
- A league-context strip below (teams, starting slots, categories or point values),
  plus a methodology note on how injuries and games played are valued.
- **Verdict first, math second:** a big verdict ("Win-win", "Accept", "Decline") with
  a one-sentence plain-language reason, then a collapsible "How we worked this out"
  block with the category-wins (or weekly-points) math. Today's `app/analysis/explain.py`
  already writes these reasons.
- **Trade finder as a feed:** ranked opportunity cards, not a form. Each card names
  both teams, what each side gains and the plain-language explanation. It's what the
  daily refresh produces; design it as a feed (it becomes the daily opportunities
  digest, moat backlog M3).
- "Show your work" blocks wherever a number appears. Trust is the product.

### 6.5 Activity

**What:** the filterable transaction log (adds, drops, trades, lineup moves).

**Why:** the queryable history is moat feature 1 made visible, and the raw material
for hindsight trade grading.

**How:** a dense table with date, team, action and player filters (keep today's);
design the row with an actions column now, so "Grade this trade in hindsight" (moat
backlog M10) slots in later.

## 7. Design system

- **Theme:** dark (every reference is; sports tools read better dark).
- **Stack:** Vite + React + Tailwind + shadcn/ui. No custom component library:
  compose shadcn primitives.
- **Type:** a condensed uppercase display font for page and section headers ("HOW
  SHOULD WE GET YOUR TEAM?"); a clean sans for body; tabular numerals for every stat.
- **Color:** blue/orange diverging scale for heatmaps; warm/cool accents for give/get;
  one set of tier colors wherever Lock / Swing / Punt appear.
- **Patterns used everywhere:** cards; slide-over detail panels (player click → stat
  grid, trend chart, how the projection was made); verdict-first blocks; collapsible
  "How we worked this out"; data-freshness pills; empty states with a next action.

## 8. API design (FastAPI, Phase 0: build first)

**Why first:** the frontend, built here or by a hire, can't start without it, and it's
pure Python. Every endpoint wraps an existing `app/queries.py`, `app/analysis/` or
`app/points/` function; no new math.

```
GET  /api/me                                               # who's signed in, their leagues, subscription
GET  /api/leagues                                          # league switcher
GET  /api/leagues/{id}/standings
GET  /api/leagues/{id}/power-rankings                      # all-play + projected finish
GET  /api/leagues/{id}/luck                                # actual vs expected wins
GET  /api/leagues/{id}/matchups?week=N
GET  /api/leagues/{id}/matchups/compare?a={team}&b={team}&week=N
GET  /api/leagues/{id}/roster-strength?window=
GET  /api/leagues/{id}/players?window=&position=&q=&hide_injured=   # rankings heatmap
GET  /api/leagues/{id}/players/{pid}                       # detail: stats, trend, projection
GET  /api/leagues/{id}/history?metric=&from=&to=           # week-over-week, from the snapshots
GET  /api/leagues/{id}/waiver-wire
GET  /api/leagues/{id}/trade-finder                        # proactive win-win feed
POST /api/leagues/{id}/trades/analyze   {give:[], get:[]}  # mock trade verdict
GET  /api/leagues/{id}/saved-trades
POST /api/leagues/{id}/saved-trades
GET  /api/leagues/{id}/transactions?from=&to=&team=&type=
POST /api/leagues/{id}/refresh                             # trigger the ingest job (authed)
POST /api/onboarding/preview            {league_id}        # today's onboarding.preview
POST /api/onboarding/register-league    {league_id, team_id}
```

Each league endpoint answers in the league's format (categories or points), the way
today's pages branch on it.

**Auth:** no usernames and passwords of our own. The site signs people in with Whop or
Google (Whop backlog R9, R10); the API checks the same sign-in's token (OpenID Connect)
on every request and maps it to the user record. Every `/api/leagues/{id}/*` endpoint
is scoped to leagues the user belongs to (today's `app/tenancy.py` and the Firestore
memberships), and to an active subscription (R12).

## 9. Phased build plan

0. **FastAPI layer** (1-2 weekends). The endpoints above, tested with curl and
   pytest. The Streamlit app is untouched and stays the live product.
1. **Scaffold and design tokens** (1 weekend). Vite + Tailwind + shadcn/ui, dark theme,
   the header with dropdowns, league switcher, sign-in flow, onboarding wizard shell.
2. **Trades page first** (2-3 weeks). The money feature: the finder feed and the mock
   trade layout (6.4). It teaches every pattern the rest reuse.
3. **Remaining pages** (1-2 weeks each, getting faster): Players (heatmaps, 6.3),
   Overview, Matchups, Activity.
4. **Polish and cutover** (1-2 weeks). Mobile bottom nav, responsiveness, empty /
   loading / error states, then cut over; Streamlit stays as an internal admin tool.
5. **Landing page** in League Winner's ad style, with checkout through Whop.

**Relation to the Whop release (decided November 1):** the product launches on this
React app, about a month before the 2027-28 preseason (about September 1, 2027), with
no Streamlit release. The dated phases are in [phase-plan.md](phase-plan.md).

## 10. What not to do

- Don't reimplement analysis math in JavaScript. Ever.
- Don't build a custom component library; shadcn/ui exists.
- Don't let the browser touch BigQuery or hold service-account keys.
- Don't polish table-stakes pages (standings, basic rankings) before the Trades page
  and the heatmaps are excellent.
- Don't nest navigation deeper than header → dropdown → section. No third level.
- Don't ship without the onboarding wizard: registration friction is the product's
  biggest conversion risk, bigger than any missing feature.

## Updates from the original draft

| Draft said | Now says | Why |
|---|---|---|
| `docs/moat.md` | `docs/whopDocs/moat.md` | Where the moat doc lives |
| ~$29-49 per league per season | Sold on Whop; price open | Pricing is Whop backlog R4 |
| Categories leagues, 14 teams | Categories and points leagues, any size | League Lab supports both formats |
| 67 analysis tests | 322 tests across the repo | Current count |
| "Idempotent MERGE" | Idempotent replace by scope, plus the snapshot tables | How the ingest writes, and the history added in M1 |
| `POST /api/auth/login {username, password}`, `manage_logins.py` | Sign-in with Whop or Google; the API checks that token; `/api/me` added | There are no app passwords; sign-in is OpenID Connect, memberships in Firestore |
| Multi-league "on the roadmap" | Multi-league exists | Users can already have several leagues |
| Private league by bookmarklet; manual set-up | Private hidden at launch; manual doesn't exist yet | Whop backlog R15 |
| Headshots, no caveat | Headshots after a lawyer check; id mapping via Wikidata | NBA images in a paid product are a rights question |
| Week-over-week deltas | Read from the snapshot tables; `/history` endpoint added | M1 now keeps the daily history |
| Checkout via Gumroad / Lemon Squeezy | Checkout through Whop | The product sells on Whop |
| `onboarding/register-league` with mode | `preview` + `register-league` | Matches today's two-step registration |
