# LeagueLabWhop: backlog

**Goal: an MVP on Whop that people can pay for.** Everything is sorted into what has to
be done before release and what can wait until after. Updated November 1, 2026.

Owner: **Eni** for decisions and accounts only you can set up, **Claude** for the build.
Size: S = under a day, M = 1-3 days, L = a week or more.

## Done

| | Done |
|---|---|
| GCP project `league-lab-whop`, budget, kill switch, alerts | Oct 18 ([product.md](product.md)) |
| Draft Tool removed from the MVP | Oct 18 ([draft-tool-removal.md](draft-tool-removal.md)) |
| Our projection model, beating ESPN's on the backtest | Oct 19 ([projections.md](projections.md)) |
| Our projections in the pages; ESPN's projections and outlooks gone | Oct 21 ([projections-in-app.md](projections-in-app.md)) |
| Nightly update: our stat windows, in-season blend, injuries, games history | Oct 29 ([nightly-update.md](nightly-update.md)) |
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
| R7 | **Use team when linking players to ESPN.** Break same-name ties by current team (Jaylin Williams, OKC) and accept a near-match name when the team agrees (ESPN's "David Jones Garcia") | Rostered players currently show no stats, which looks broken to a paying customer | S |
| R8 | **Double-doubles in points leagues, minimum version.** Count double-doubles and triple-doubles in the actual-stat windows from our box scores, and tell the user at sign-up that projected bonuses aren't counted yet | A league paying for double-doubles undervalues big men by up to ~4 points a game, with no warning | S-M |

### Accounts and payment (Claude, after R3 and R4)

| # | Item | Why it blocks release | Size |
|---|---|---|---|
| R9 | **Choose the sign-in.** Test whether Whop's sign-in works with Streamlit's login (one account, membership included); otherwise Google sign-in plus a Whop membership check | Nobody can sign in to `league-lab-whop` today | S |
| R10 | **Set up the sign-in** (client and secret `league-lab-auth`; Google needs R5's domain and a published privacy policy) | Same | S |
| R11 | **Whop webhook.** A small Cloud Run function that verifies Whop's events and records each user's subscription in Firestore, plus a daily check against Whop's API for missed events | The site has to know who paid | M |
| R12 | **The gate.** `app/tenancy.py` checks for an active subscription instead of the allowlist. A lapsed membership stops refreshing; after a grace period its leagues are purged | Only paying users get in | M |
| R13 | **Plan caps.** Leagues per user from the plan; raise the site-wide league cap | Today it's 10 leagues total, 3 per user | S |
| R14 | **Cost guardrails for a paid site.** Budget alerts email first; the kill switch moves to a much higher ceiling; BigQuery's daily cap rises to match | The $5 kill switch would shut paying customers out | S |
| R15 | **Public leagues only at launch.** Hide the "save your ESPN login" path for private leagues | Holding customers' ESPN logins raises the security and legal bar; a later decision | S |

### Public face (Claude, after R1 and R5)

| # | Item | Why it blocks release | Size |
|---|---|---|---|
| R16 | **Privacy policy and terms**, rewritten for paying users using the lawyer's answers: what we store, deletion, refunds, "not affiliated with ESPN" | Required by Whop, by Google's sign-in and by law | M |
| R17 | **Wording pass.** No ESPN logos or look-alike branding; "works with ESPN fantasy basketball leagues"; no page claims ESPN as its source | Lawyer question 2; the pages were written for a personal tool | S |
| R18 | **Custom domain** on the site | Sign-in and the Whop listing need it | S |
| R19 | **Whop listing.** Description, screenshots, plans, support email | It's the storefront | S |

### Launch

| # | Item | Size |
|---|---|---|
| R20 | **Full rehearsal:** a test purchase, sign-in, registering a public league, the next morning's refresh, cancelling, the grace period and purge | S |
| R21 | **Soft launch** to a small first group; watch cost per league and the alerts for a week before opening wider | - |

**Order:** R7-R8 now (no dependencies) → R9-R15 once the Whop account and plans exist →
R16-R19 once the lawyer and domain are settled → R20-R21.

## After release

| # | Item | Why it can wait | Size |
|---|---|---|---|
| P1 | **Batch the per-league BigQuery writes** (one load per table per run). Do it **before passing ~15 leagues** | The free BigQuery tier covers about 18 leagues; cost only matters past that | M |
| P2 | **NBA schedule from BallDontLie.** First compare it with ESPN's every night (date to ESPN's daily scoring period and matchup week); switch once they agree through the NBA Cup schedule changes in December | A schedule is plain facts and saves only one ESPN request per points league; nice to have, not required | M |
| P3 | **Rookie projections.** A rookie model from draft position and college or overseas stats; also lifts the in-season rookie blend (about 2 fantasy points a game low) | The in-season blend already projects rookies once they play; preseason work isn't a priority | L |
| P4 | **Better preseason model.** Stars still run a bit low against ESPN (top 50: −1.9 vs −0.3); free throws lag | Already beats ESPN overall; preseason isn't a priority mid-season | M |
| P5 | **Projected double-doubles**, from each player's double-double rate, and accepting categories leagues that score them | R8 covers actual stats and warns; this completes it | M |
| P6 | **Projections methodology page** ("how our numbers are made") | A selling point, not a requirement | S |
| P7 | **Private leagues** (customers' saved ESPN logins), as a deliberate decision with the lawyer | Launch is public leagues only (R15) | M |
| P8 | **Other points-league stats** beyond our 15 (fouls, ejections ...) | They count 0 today; rare in real leagues | S |
| P9 | **Draft Tool back**, built on our own rankings instead of ESPN's ADP | Out of the MVP by decision; next useful before the 2027-28 drafts | L |
| P10 | **Season rollover** for 2027-28: preseason projections, new season's leagues, history | Not needed until next fall | M |
