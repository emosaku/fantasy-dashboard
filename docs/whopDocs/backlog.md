# LeagueLabWhop: backlog

**Goal: an MVP on Whop that people can pay for.** Everything is sorted into what has to
be done before release and what can wait until after. Updated November 1, 2026.

Owner: **Eni** for decisions and accounts only you can set up, **Claude** for the build.
Size: S = under a day, M = 1-3 days, L = a week or more.

**Priority rule ([moat.md](moat.md)):** deepen a moat feature first (league history,
the trade finder, luck analysis, Lock / Swing / Punt tiers); keep table-stakes features
competitive without gold-plating; everything else last. Moat items are numbered M.

## Done

| | Done |
|---|---|
| GCP project `league-lab-whop`, budget, kill switch, alerts | Oct 18 ([product.md](product.md)) |
| Draft Tool removed from the MVP | Oct 18 ([draft-tool-removal.md](draft-tool-removal.md)) |
| Our projection model, beating ESPN's on the backtest | Oct 19 ([projections.md](projections.md)) |
| Our projections in the pages; ESPN's projections and outlooks gone | Oct 21 ([projections-in-app.md](projections-in-app.md)) |
| Nightly update: our stat windows, in-season blend, injuries, games history | Oct 29 ([nightly-update.md](nightly-update.md)) |
| Daily league snapshots (M1): rosters, standings, category ranks, player values, injuries | Nov 1 ([snapshots.md](snapshots.md)) |
| Bonus stats counted: double-doubles, triple-doubles, quadruple-doubles, fouls, foul-outs, misses (was R8, done in full) | Nov 1 ([bonus-stats.md](bonus-stats.md)) |
| Questions for a lawyer | Oct 28 ([legal-questions.md](legal-questions.md)) |

## Before release

### Start now (Eni, in parallel with the build)

| # | Item | Why it blocks release | Size |
|---|---|---|---|
| R1 | **Lawyer consult.** Bring [legal-questions.md](legal-questions.md) | ESPN's API, the name "ESPN", privacy terms and an LLC all need an answer before charging anyone | - |
| R2 | **Business entity decision** (LLC or personal), from the consult | Whop payouts, the terms and liability depend on it | - |
| R3 | **Whop seller account** | Payment, webhooks and possibly sign-in run through it | S |
| R4 | **Plans and prices.** Leagues per plan (e.g. 1, or up to 3), monthly vs per season, free trial length | The gate and the caps are built from these | S |
| R5 | **Product name and domain.** Buy the domain | The sign-in screen, privacy policy and Whop listing all show it | S |
| R6 | **Support email** on that domain | Required on the Whop listing and the site | S |

### Data fixes (Claude)

| # | Item | Why it blocks release | Size |
|---|---|---|---|
| R7 | ~~Use team when linking players to ESPN~~ **Done Nov 1**: Jaylin Williams (OKC) and David Jones (ESPN's "David Jones Garcia") linked ([nightly-update.md](nightly-update.md)) | | |
| R8 | ~~Double-doubles in points leagues~~ **Done Nov 1**, actual and projected ([bonus-stats.md](bonus-stats.md)) | | |
| R8a | ~~Alert when a league's points check jumps~~ **Done Nov 1** ([bonus-stats.md](bonus-stats.md)) | | |
| R8b | ~~Note on the points pages naming uncounted stats~~ **Done Nov 1** | | |

### Moat items that can't wait (Claude)

| # | Item | Why it blocks release | Size |
|---|---|---|---|
| M1 | ~~Daily league snapshots~~ **Done Nov 1** ([snapshots.md](snapshots.md)) | | |
| M2 | **Keep history after a lapse.** A lapsed or cancelled league stops refreshing but keeps its history for a set time (e.g. 12 months) so a returning customer finds it intact; deleted on request. Changes R12's purge and goes in R16's privacy policy | Purging on lapse throws the moat away | S |

### Accounts and payment (Claude, after R3 and R4)

| # | Item | Why it blocks release | Size |
|---|---|---|---|
| R9 | **Choose the sign-in.** Test whether Whop's sign-in works with Streamlit's login (one account, membership included); otherwise Google sign-in plus a Whop membership check | Nobody can sign in to `league-lab-whop` today | S |
| R10 | **Set up the sign-in** (client and secret `league-lab-auth`; Google needs R5's domain and a published privacy policy) | Same | S |
| R11 | **Whop webhook.** A small Cloud Run function that verifies Whop's events and records each user's subscription in Firestore, plus a daily check against Whop's API for missed events | The site has to know who paid | M |
| R12 | **The gate.** `app/tenancy.py` checks for an active subscription instead of the allowlist. A lapsed membership stops refreshing and keeps its history (M2) | Only paying users get in | M |
| R13 | **Plan caps.** Leagues per user from the plan; raise the site-wide league cap | Today it's 10 leagues total, 3 per user | S |
| R14 | **Cost guardrails for a paid site.** Budget alerts email first; the kill switch moves to a much higher ceiling; BigQuery's daily cap rises to match | The $5 kill switch would shut paying customers out | S |
| R15 | **Public leagues only at launch.** Hide the "save your ESPN login" path for private leagues | Holding customers' ESPN logins raises the security and legal bar; a later decision | S |

### Public face (Claude, after R1 and R5)

| # | Item | Why it blocks release | Size |
|---|---|---|---|
| R16 | **Privacy policy and terms**, rewritten for paying users using the lawyer's answers: what we store, how long history is kept after a lapse (M2), deletion, refunds, "not affiliated with ESPN" | Required by Whop, by Google's sign-in and by law | M |
| R17 | **Wording pass.** No ESPN logos or look-alike branding; "works with ESPN fantasy basketball leagues"; no page claims ESPN as its source | Lawyer question 2; the pages were written for a personal tool | S |
| R18 | **Custom domain** on the site | Sign-in and the Whop listing need it | S |
| R19 | **Whop listing.** Description, screenshots, plans, support email | It's the storefront | S |

### Launch

| # | Item | Size |
|---|---|---|
| R20 | **Full rehearsal:** a test purchase, sign-in, registering a public league, the next morning's refresh and snapshot, cancelling, history kept, deletion on request | S |
| R21 | **Soft launch** to a small first group; watch cost per league and the alerts for a week before opening wider | - |

**Order:** R7, R8a-b and M1 now (no dependencies; M1 first, since its value grows
with every day it runs) → R9-R15 and M2 once the Whop account and plans exist →
R16-R19 once the lawyer and domain are settled → R20-R21.

## After release

### Moat work first

In this order (moat features ahead of everything else; see [moat.md](moat.md)):

| # | Moat | Item | Why this spot | Size |
|---|---|---|---|---|
| M3 | Trade finder | **Daily opportunities digest:** each morning's new win-win trades and pickups for my team, ranked and explained, by email | The most visible "it works for me while I sleep" feature; builds the email sending M9 and M12 reuse | M |
| M4 | Luck | **Luck-adjusted ("deserved") standings** in Power Rankings | Small; uses all-play data we already keep | S |
| M5 | History | **Past seasons at sign-up:** load a new league's earlier seasons from ESPN (results, standings, trades) | A new customer has history on day one | M |
| M6 | History | **Manager profiles:** who trades, streams, punts, sells low, from the transaction log | Uses data we already keep | M |
| M7 | Trade finder | **Counter-offer generator:** for a lopsided offer, the smallest change that makes it win-win | Builds directly on the trade finder | M |
| M8 | Tiers | **Punt optimizer:** which categories to punt and the expected standings gain | Extends the tiers into a decision | M |
| M9 | Luck | **Weekly luck recap** in plain words, ready to paste into the league chat; plus regression candidates (teams and players due to come back to earth) | Shareable, so it brings in new leagues | S-M |
| M10 | History | **Hindsight trade grading:** each past trade graded by what happened after, against how it looked that day | Needs M1's snapshots from the day of the trade, so after a few weeks of them | M |
| M11 | Tiers | **Tier changes over time:** which categories are slipping from Swing toward Punt | Needs M1's snapshots | S |
| M12 | Trade finder | **Watchlist alerts:** tell me when a trade I wanted becomes possible (injury, slump, schedule) | Needs M3's notifications | M |
| M13 | Tiers | **Points-league tiers:** where my points come from versus the league, the points version of Lock / Swing / Punt | Tiers exist for categories leagues only | M |
| M14 | History | **Season archives and "on this date last year"** | Needs a season of snapshots | M |
| M15 | Tiers | **Draft-day punt targets:** players whose value sits in the categories you keep | Belongs with the Draft Tool's return (P9) | M |

### Everything else

| # | Item | Why it can wait | Size |
|---|---|---|---|
| P1 | **Batch the per-league BigQuery writes** (one load per table per run). Do it **before passing ~15 leagues** | The free BigQuery tier covers about 18 leagues; cost only matters past that | M |
| P2 | **NBA schedule from BallDontLie.** First compare it with ESPN's every night (date to ESPN's daily scoring period and matchup week); switch once they agree through the NBA Cup schedule changes in December | A schedule is plain facts and saves only one ESPN request per points league; nice to have, not required | M |
| P3 | **Rookie projections.** A rookie model from draft position and college or overseas stats; also lifts the in-season rookie blend (about 2 fantasy points a game low) | The in-season blend already projects rookies once they play; preseason work isn't a priority | L |
| P4 | **Better preseason model.** Stars still run a bit low against ESPN (top 50: −1.9 vs −0.3); free throws lag | Already beats ESPN overall; preseason isn't a priority mid-season | M |
| P5 | **Weekly total check**: each team's actual weekly score from ESPN against its starters' points by our math | Catches team-level problems the per-player check can't; R8a covers most cases | M |
| P6 | **Projections methodology page** ("how our numbers are made") | A selling point, not a requirement | S |
| P7 | **Private leagues** (customers' saved ESPN logins), as a deliberate decision with the lawyer | Launch is public leagues only (R15) | M |
| P8 | **Stats our source doesn't report**: ejections, flagrant and technical fouls, games started, team wins. Needs another source, or an estimate (starters from minutes) | Rare in real leagues; shown as not counted (R8b) | M |
| P9 | **Draft Tool back**, built on our own rankings instead of ESPN's ADP | Out of the MVP by decision; next useful before the 2027-28 drafts | L |
| P10 | **Season rollover** for 2027-28: preseason projections, new season's leagues, history | Not needed until next fall | M |
