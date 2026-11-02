# League Lab React rebuild: phase plan to a September 2027 launch

**November 1, 2026.** Online copy: https://claude.ai/artifact/GbfxcP26hcjWtNPnESE9iS.
League Lab launches on Whop as a React app around **September 1, 2027**, a month
before the 2027-28 preseason. There's no release this season and no Streamlit release.

## Decisions

- **Launch date:** about a month before the 2027-28 NBA preseason. The preseason
  usually starts in early October, so the target is about September 1, 2027; it moves
  when the schedule is published. People buy fantasy tools at draft time.
- **React only.** The Streamlit app is never sold; it stays as an internal admin tool
  after cutover.
- **No release this season.** The Whop backlog's Streamlit-only items (hiding the
  private-league path, the wording pass, screenshots) move into the React phases.
- **Branch:** `ReactFrontend` is the release branch. Backend work planned on
  `WhopVersion` (sign-in, paywall, history retention, cost limits) is built here.
- **This season still counts.** `league-lab-whop` keeps running every morning.
  Registering real leagues there now builds months of daily snapshots by launch, the
  history behind week-over-week changes and hindsight grading, and the real data the
  new pages are tested against.

A draft-time launch needs good preseason projections, rookie projections and arguably
a draft tool, all "not now" items for a mid-season launch. Phase 8 covers them.

## Schedule

| Phase | Target | Effort |
|---|---|---|
| 1 API foundation | Nov 2 to Nov 30 | 1-2 weekends |
| 2 Scaffold and sign-in | Dec 1 to Dec 15 | 1 weekend |
| 3 Trades page | Dec 15 to Jan 31 | 2-3 weekends |
| 4 Remaining pages | Feb 1 to Mar 15 | 5-6 weekends |
| 5 Onboarding | Mar 1 to Mar 31 | 2 weekends |
| 6 Live trial | Mar 15 to Apr 30 | through the fantasy playoffs |
| 7 Moat features | May 1 to Jun 30 | 4-6 weekends |
| 8 Draft-season readiness | Jun 15 to Aug 15 | 4-6 weekends |
| 9 Business, payment, public face | Jun 1 to Aug 20 | 4-5 weekends |
| 10 Rehearsal and launch | Aug 20 to Sep 1 | 1-2 weekends |

About 30 weekends of build over 10 months, so there's slack. The trial has to happen
before mid-April, when the NBA season ends; the rest can slide a few weeks without
moving the launch.

**Needed from you, and by when:**

| Item | Needed by | Unblocks |
|---|---|---|
| Register your leagues in league-lab-whop (public), plus a friend's if possible | November | Months of snapshots by launch; the Phase 6 trial |
| Lawyer consult (legal-questions.md, plus NBA headshots) | February | Private leagues, headshots, naming ESPN, the privacy policy |
| Whop seller account (and a developer app for the sign-in spike) | November for the spike; May for payments | Phase 1 spike; Phase 9 |
| LLC or personal | May | Whop payouts, terms |
| Plans and prices | June | Paywall and plan caps |
| Product name and domain | June | Landing page, sign-in screen, listing |
| Support email on the domain | July | Whop listing |
| Draft Tool: in or out | June | Phase 8 |

## Phase 1: API foundation (November, 1-2 weekends)

**Built November 1** ([phase1-api.md](phase1-api.md)): every item below done; the new SQL is waiting for review before it runs on `league-lab-whop`.

A FastAPI layer over the existing queries and analysis code, a cache for the trade
finder, a history view over the snapshots, and two spikes. No UI. The data model is
already multi-league (every table has `league_id`; the ingest loops over the Firestore
league registry), so there's no schema migration.

```
Read docs/reactDocs/ui-rebuild-plan.md, docs/reactDocs/phase-plan.md and
docs/whopDocs/moat.md. Build the FastAPI layer in api/ from section 8 of the rebuild
plan: every endpoint wraps an existing function in app/queries.py, app/analysis/ or
app/points/, answers in the league's format (categories or points), and adds no new
math. Tests first, against tests/fixtures/four_team_league.py and
tests/fixtures/points_league.py. Add a cache table for the trade finder's results,
written after each morning's ingest for every league, and a view over the snap_*
tables for week-over-week rank changes (GET /history). Sign-in: verify an OpenID
Connect token behind one function so Whop or Google can be plugged in; until R9 is
decided, a test issuer stands in. Don't change the ingest's tables or how it writes.
Show me any new BigQuery SQL before running it against league-lab-whop. Start in
plan mode.
```

- [x] Every endpoint has a test; median response under 200 ms from the m_* tables and the finder cache
- [x] A request for a league the user doesn't belong to returns 403
- [x] The daily ingest and the nightly NBA update still run green
- [x] The history view returns week-over-week rank changes from the snapshots
- [x] Spike written up: can Whop's sign-in act as an OpenID Connect provider for both Streamlit and the API (decides R9)
- [x] Spike written up: can a bookmarklet read espn_s2 and SWID, or which fallback for private leagues (research only; private leagues need the lawyer first)

## Phase 2: scaffold and sign-in (December, 1 weekend)

```
Scaffold web/ per section 7 of docs/reactDocs/ui-rebuild-plan.md: Vite + React +
Tailwind + shadcn/ui, dark theme tokens. Build the global chrome from section 5:
sticky header with hover dropdowns that deep-link to route#anchor with a highlight
pulse, league switcher (each league is categories or points), data-freshness pill
with manual refresh, avatar menu (league admin, privacy, subscription), and a 5-icon
bottom tab bar under 768px. Sign-in uses the provider chosen in the Phase 1 spike
(Whop, or Google): no third auth provider. Generate the TypeScript API client from
FastAPI's OpenAPI schema. Check it at 1280px and 390px before you finish.
```

- [ ] Sign-in works end to end; the token reaches the API and the API accepts it
- [ ] /trades#finder loads scrolled to the section with the pulse
- [ ] The league switcher swaps between a categories and a points league
- [ ] Header and bottom tabs look right at 1280px and 390px

## Phase 3: Trades page (December to January, 2-3 weekends)

```
Build /trades per section 6.4 of docs/reactDocs/ui-rebuild-plan.md, for categories
and points leagues. Start with the trade finder feed as ranked opportunity cards,
then the You give / You get mock trade with the verdict first and a collapsible
show-your-work block (the reasons come from app/analysis/explain.py and app/points/).
Then Create a trade, Team profile and Saved trades. All numbers come from the API;
if a number you need isn't in an endpoint, stop and propose an API change instead of
computing it. Build reusable components in web/src/components/patterns as you go.
```

- [ ] Finder results and verdicts match the Streamlit app for the same day's data, in both formats
- [ ] Mock trade works on a phone with tap-to-add (no drag needed)
- [ ] Diff reviewed against docs/whopDocs/moat.md: the finder still models every roster in the league

## Phase 4: remaining pages (February to March, 5-6 weekends)

Players, Overview, Matchups, Activity, in that order; a fresh session per page, each
in both formats.

```
Build /players per section 6.3 of docs/reactDocs/ui-rebuild-plan.md, reusing
web/src/components/patterns, for categories and points leagues. First: Lock / Swing /
Punt tier pills, sortable sticky headers, the pinned my-team row, week-over-week rank
changes from GET /history. Then hover tooltips with the underlying values and
select-two-to-compare linking to /matchups#compare. Blue/orange diverging scale. On
points leagues, show the note naming scored stats we can't count (today's
app/points/view.py header).
```

The same prompt with the page swapped: Overview (6.1), Matchups (6.2), Activity (6.5).

- [ ] Every Streamlit capability has a home in the new app: a checklist mapping each old page and tab (categories and points) to its new section
- [ ] The heatmap scale passes a colorblind simulator check
- [ ] Activity rows have an actions column ready for hindsight trade grading
- [ ] Player headshots only if the lawyer clears them; otherwise initials or team logos

## Phase 5: onboarding (March, 2 weekends)

```
Build the onboarding wizard per section 5 of docs/reactDocs/ui-rebuild-plan.md: the
Public league card (recommended), a segmented progress bar, one question per screen,
back navigation, and "not affiliated with ESPN" on every step. Show the Private league
and Set up by hand cards only if the lawyer and the Phase 1 spike cleared them. Wire it
to POST /api/onboarding/preview (today's app/onboarding.py preview: format locked for
the season, categories or point values, scored stats we can't count) and POST
/api/onboarding/register-league, which registers the league (app/tenancy.py), starts
its first refresh and reports status until its data is ready.
```

- [ ] A public league goes from a pasted ESPN link to a working dashboard with no help from you
- [ ] A league with stats we can't count shows the warning before registering
- [ ] If private leagues are cleared: cookies go straight to Secret Manager and nothing appears in logs

## Phase 6: live trial (March to April, through the fantasy playoffs)

Real managers use the new app on real leagues for the rest of the season, with
Streamlit still there as a fallback.

```
Do a polish pass across all five pages: loading, empty and error states with a next
action; a responsiveness pass at 390px, 768px and 1280px; consistent tier colors and
tabular numerals. Then write the deploy steps for the api and web services on Cloud
Run in league-lab-whop, but don't run any gcloud deploy commands; I'll run them.
```

- [ ] No page shows a blank screen on a slow or failed request
- [ ] Your leagues and at least one friend's league use it for 3+ weeks with no Streamlit fallback needed
- [ ] Both a categories and a points league go through the trial
- [ ] A list of what trial users asked for or tripped on, triaged into Phase 7 or after launch

## Phase 7: moat features (May to June, 4-6 weekends)

| Item | Moat | For launch |
|---|---|---|
| M3 Daily opportunities digest (by email) | Trade finder | Yes |
| M10 Hindsight trade grading | History | Yes: 6+ months of snapshots by May |
| M5 Past seasons at sign-up | History | Yes: at draft time a league has no games, so past seasons are its history |
| M4 Luck-adjusted ("deserved") standings | Luck | Yes |
| M11 Tier changes over time | Tiers | Yes |
| M13 Points-league tiers | Tiers | Yes |
| M6 Manager profiles, M7 Counter-offers, M8 Punt optimizer, M9 Weekly luck recap, M12 Watchlist alerts | Mixed | If there's room |

Kickoff per item: "Build M<n> per docs/whopDocs/moat.md and backlog.md: the math in
Python behind an API endpoint with tests first, then its home in the React page." M3
needs an email provider (a small decision in this phase).

## Phase 8: draft-season readiness (June to August, 4-6 weekends)

- **Season rollover (P10):** 2027-28 preseason projections, the new season in both
  nightly jobs, leagues registering for the new season, and every page's preseason
  state (no standings or matchups yet: show projections and last season).
- **Rookie projections (P3):** the 2027 draft class needs a preseason line. BallDontLie
  has no college stats, so this needs a source decision.
- **Better preseason model (P4):** the top-50 gap with ESPN, and free throws.
- **Draft Tool (P9), decide by June:** built on our own projections it no longer needs
  ESPN's ADP. Recommendation: include it, as a sixth destination or under Players.

- [ ] A league registered in August for 2027-28 shows useful pages before its draft
- [ ] 2027-28 preseason projections backtested like this season's
- [ ] Draft Tool decided, and built if yes

## Phase 9: business, payment and public face (June to August, 4-5 weekends)

| Item | What | Backlog |
|---|---|---|
| Whop webhook | Verifies Whop's events, records each subscription in Firestore, daily check for missed events | R11 |
| Paywall | Checked in the API, never the UI | R12 |
| History kept after a lapse | Stops refreshing, keeps history for a set time; deleted on request | M2 |
| Plan caps | Leagues per user from the plan | R13 |
| Cost limits for a paid site | Alerts first; kill switch at a much higher ceiling; BigQuery cap raised | R14 |
| Batched BigQuery writes | One load per table per run, before about 15 leagues | P1 |
| Privacy policy and terms | From the lawyer's answers | R16 |
| Wording pass | No ESPN branding; "works with ESPN fantasy basketball leagues" | R17 |
| Custom domain | On the web and api services | R18 |
| Landing page | League Winner style: proof-number headline, "We model your entire league, not just your team", verb-first benefits, real screenshots; links into onboarding | |
| Whop listing | Description, screenshots, plans, support email | R19 |

- [ ] A test purchase unlocks a league; a refund or cancellation locks it again and keeps its history
- [ ] The landing page works on a phone and links straight into onboarding
- [ ] Privacy policy and terms published on the custom domain

## Phase 10: rehearsal and launch (late August to about September 1)

- **Rehearsal (R20):** a stranger's path end to end: land, buy on Whop, sign in,
  register a public league, the next morning's refresh and snapshot, the digest email,
  cancel, history kept, deletion on request.
- **Soft launch (R21):** a small first group for a week, watching cost per league, the
  alerts and support email.
- **Open:** the Whop listing goes public about a month before the preseason.

## What was corrected from the proposal

| Proposal said | Now | Why |
|---|---|---|
| Paid beta in 13-15 weekends (mid-February) | Launch about September 1, 2027 | Launch into draft season |
| Phase 1: `league_id` everywhere, a new leagues table, backfill your league | Dropped | Already multi-league; a new leagues table would replace working code |
| A cache of every endpoint | Finder cache only | The `m_*` tables cache the rest |
| A snapshot view to build | A view over the existing snapshots | M1 exists since November 1 |
| "A managed auth provider" | Whop or Google, decided by a spike | Membership comes with sign-in |
| "All 14 rosters", "your 14 managers" | Every roster, any size, both formats | The product supports both formats |
| Private-league path in onboarding | Only if the lawyer clears it | A security and legal decision |
| Lemon Squeezy per league per season | Whop, plans from R4 | The product sells on Whop |
| Your 14 managers for a week | A live trial on your and a friend's leagues through the playoffs | Your league lives in other projects and may be private |
| `docs/ui-rebuild-plan.md`, `docs/moat.md` | `docs/reactDocs/`, `docs/whopDocs/` | Where the docs live |
| Not covered | Phases 7, 8 and most of 9 | Needed before anyone pays, and for a draft-time launch |

**After launch:** private leagues (if not cleared before), stats our source doesn't
report (P8), the weekly total check (P5), a methodology page (P6), the NBA schedule
from BallDontLie (P2), and the moat features that didn't fit Phase 7.
