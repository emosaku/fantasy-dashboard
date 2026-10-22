# LeagueLabWhop: Questions for a Lawyer

October 22, 2026 · Online copy: https://claude.ai/artifact/E3HFXVk5x6PfyTjqYKn7ft

## Background

LeagueLabWhop is a paid analytics website for ESPN fantasy basketball leagues, to be sold as a subscription on Whop. It hasn't launched and has no customers yet. A customer connects their own ESPN league, and the site shows analysis ESPN doesn't: power rankings, luck, trade suggestions and our own player projections. It is a solo project by one person, run on Google Cloud.

What the site uses, and where each part comes from:

| Data | Source | How we get it | Terms |
| --- | --- | --- | --- |
| The customer's league: teams, rosters, matchups, settings, transactions | ESPN | ESPN's unofficial website API, read once a day for public leagues the customer registers | ESPN's site terms; no license or agreement with ESPN |
| NBA schedule, player injury status, current-season stats | ESPN | Same API | Same |
| NBA game-by-game player stats, 2016-17 onward | [BallDontLie](https://www.balldontlie.io/terms), paid plan ($9.99/month) | Their official API | Their terms allow commercial use; they forbid reselling the raw data or building a competing data service |
| Player birth dates, player ID links | [Wikidata](https://www.wikidata.org/wiki/Wikidata:Licensing) | Public query service | CC0 public domain |
| Player projections | Our own model, built from the BallDontLie stats | Calculated by us | Ours |

Already done to reduce risk: ESPN's own projections, rankings, draft data and written player analysis were removed from the product. We store a one-time copy of ESPN's preseason projections privately to measure our model against; no customer sees it.

This is a set of questions, not a request for a full review. Where a question has a yes/no answer, that is all that's needed.

## ESPN

The biggest risk: the product depends on ESPN's unofficial API, and ESPN's terms limit automated access and commercial use.

1. Is it legally acceptable to sell a product that reads a customer's own ESPN league through ESPN's unofficial API, with the customer's permission?
2. ESPN's terms restrict automated access and commercial use. Does breaking website terms create real legal exposure (breach of contract, computer-access laws), or mainly the risk of being blocked?
3. Does it matter that we never log in as the customer for public leagues, only read what ESPN shows anyone?
4. If ESPN sends a cease-and-desist, what must we do, and how fast? Is shutting down ESPN access enough, or can they seek damages for past use?
5. We show actual player stats and injury statuses that ESPN serves. Are those safe because they are facts, or is ESPN's compilation of them protected? Should we move them to the licensed source (BallDontLie) before launch?
6. We keep a private copy of ESPN's preseason projections to test our model, never shown to customers. Is that internal use a problem?
7. Private ESPN leagues need the customer's ESPN login cookies, which work like a password. If we add them later, what extra obligations would storing them bring? Should we keep them out of the product entirely?
8. Would asking ESPN for permission or a license help or hurt?

## Other data sources

These look lower-risk; the questions confirm that before we rely on them.

1. BallDontLie's [terms](https://www.balldontlie.io/terms) allow commercial use and redistribution, but forbid selling the data "in its original, unmodified form" and building "products or services that compete with us." Our pages show per-game averages and last-7/15/30-day averages calculated from their game stats, next to our own projections. Is that "modified" enough? Could a fantasy analytics site count as competing with them?
2. BallDontLie's terms say they don't guarantee where their data comes from. If their data turns out to be scraped from the NBA or someone else, are we exposed for using it?
3. Are NBA box-score statistics free to use as facts (we understand US courts have treated them that way), and does that hold for a paid product?
4. Wikidata's data is CC0 public domain. Is there anything to watch for using it commercially, such as attribution?
5. Our projections are calculated from these stats. Do we fully own them, and can we stop others from copying them?

## Names and branding

The product needs to say what it works with without looking endorsed by ESPN or the NBA.

1. Can we say "works with ESPN fantasy basketball leagues" on the Whop listing and the site? Does it need a "not affiliated with or endorsed by ESPN" line, and where?
2. Can we use NBA team names and abbreviations (DEN, LAL) and players' names throughout the site? Is there any issue with player names in marketing, such as "see where Jokić ranks"?
3. Is player-name use affected by publicity rights or by the NBA players' union's group licensing, given we only show stats and analysis?
4. Before picking a product name: what should we check (trademark search), and is it worth registering one at launch?
5. Any wording to avoid in marketing, such as "better than ESPN's projections", even if our backtest shows it?

## Customer data and privacy

We store little: each customer's email and name from sign-in, the ESPN league IDs they register, saved trades, and their league's data as ESPN shows it, including the names ESPN shows for other people in the league. Payment is handled by Whop; we never see card details.

1. What must the privacy policy cover, and can it be short and plain? Is there a template you'd recommend?
2. A league's data includes the names of other managers in that league, who never signed up with us. Is showing and storing that a problem?
3. Which privacy laws apply to a small US product sold worldwide through Whop: state laws like California's, and Europe's GDPR if someone in Europe subscribes? Do we need to block or handle any regions?
4. What do we have to offer for deleting a customer's data, and how fast? (The site can already delete a league and all its data.)
5. Is there any age limit to state (for example, 18+ or 13+), given fantasy sports with no money prizes?
6. If our cloud account were ever breached, what would we have to do and by when?

## Selling on Whop

The plan is a monthly or per-season subscription on Whop, priced by the number of leagues, with a short free trial.

1. What must our own terms of service say, beyond Whop's? In particular: the service depends on ESPN, which can change or block access at any time.
2. If ESPN blocks us and the product stops working mid-season, what do we owe subscribers? Should the terms promise prorated refunds?
3. What disclaimers do projections and trade suggestions need ("for entertainment, no guarantee of results")? Does fantasy sports with no money prizes keep us clear of gambling rules, and do we need to say so?
4. Does Whop's seller agreement shift any risk to us we should know about, such as chargebacks or content takedowns?
5. Sales tax and VAT: does Whop collect and remit them as the seller of record, or are we responsible? Anything to register for?
6. How should the income be reported, and does it need a separate bank account from day one?

## Business setup and personal liability

Today this is one person's side project, billed to a personal Google Cloud account.

1. Should this run under an LLC before the first sale? Which state, given where I live? Does an LLC actually protect personal assets if ESPN or a customer brings a claim?
2. Is business insurance (general or tech liability) worth it at this size?
3. My day job: what in my employment agreement should I check (invention assignment, side-business, conflict-of-interest clauses)? Does it matter that I build it on my own time and hardware? Should I tell my employer, or get written sign-off?
4. The code was written with an AI coding assistant. Does that affect who owns it or whether it can be protected?
5. If the product is later sold, or a partner joins, what should be set up now so ownership is clean?

## Before the meeting

If there's only an hour, ask these first. Each one could stop the launch or change how it's built:

1. ESPN, questions 1, 2 and 4: can we sell it at all, and what happens if ESPN objects?
2. Business setup, question 3: does my employment agreement allow it?
3. Business setup, question 1: LLC before the first sale?
4. Names and branding, question 1: can we say "works with ESPN"?
5. Selling on Whop, question 2: what do we owe customers if ESPN cuts us off?

To bring:

- [ ] My employment agreement and any employee handbook sections on side work and inventions
- [ ] ESPN's terms of use (current version)
- [ ] [BallDontLie's terms](https://www.balldontlie.io/terms) and Whop's seller terms
- [ ] A draft of the Whop listing text and the planned product name
- [ ] This document, with the Background table
