# Trade Analyzer: how it works

*Last updated October 7, 2026.*

## Overview

The Trade Analyzer answers one question: **which moves win your team more categories?** It works for your own team (the league commissioner can pick any team), and every number on it comes from the same model, so a deal shows the same result on every tab.

| Tab | What it's for |
| --- | --- |
| **Team profile** | Where you stand in each category, and which ones to protect, chase or give up |
| **Waiver wire** | The best "add this free agent, drop that player" moves |
| **Trade finder** | Every 1-for-1 and 2-for-1 deal with every team that helps both sides |
| **Create a trade** | Pick a player you want, or a trade block you'd move (Offer Builder); get the best offers. *New:* three-team deals |
| **Mock trade** | Try any deal, plus your own adds and drops around it, and see the result step by step. *New:* three-team deals |

Three controls at the top shape everything below them:

- **Stats from**: which numbers to judge players on. *Blended* uses ESPN's projection early in the season and shifts to real season stats as games are played. *Projected* uses ESPN's projections only.
- **Swing size**: how big a realistic gain or loss in one category is (1.0 is about one solid starter). It decides which categories count as close races.
- **Category strategy**: override any category to Lock, Swing or Punt. A punted category stops counting for you everywhere on the page.

## How deals are scored

**Player value (z-scores).** Each player gets a score in each of the 9 categories: how far above or below the league's typical player he is. 0 is average and +1 is a clearly above-average contributor. Percentages are weighted by volume, so a 50% shooter on 2 shots a game doesn't outrank a 48% shooter on 20. A team's strength in a category is the sum of its healthy players' scores. Players on IR don't count.

**Category wins (E).** The main number on the page. It counts how many categories your team would win if it played every other team at once: 9 categories × 13 opponents = 117 possible, with ties counting half. A deal is judged by how much it changes this. **"+3 category wins"** means your team now beats three more opponent-category pairs. For example, it passes 2 teams in assists and 1 in steals.

**Tiers.** Each category gets a tier from the standings:

- **Lock**: you're comfortably ahead.
- **Swing**: you're in a close race.
- **Punt**: you're too far behind to catch up.

Punted categories don't count in your E, so the analyzer won't push you to chase a category you've given up. You can override any tier.

**Value to you vs. general value.** *Value to you* weights each category by your tiers: a player strong in your Swing categories is worth more to you than to someone who has them locked. *General value* is the plain total, the same for everyone, and close to how ESPN's rankings would see a player. The Trade finder and Create a trade use it as a fairness check.

**Empty roster spots** *(new)*. If a move leaves you a player short, the open spot is scored as **a player with no stats**: clearly negative in counting categories, and neutral in percentages, since no shots taken means your percentages don't move. Before, an open spot quietly counted as an average player, which made 2-for-1 deals look better than they were and made every pickup look worthless.

## Team profile and Waiver wire

**Team profile** shows your category wins against everyone (out of 117) and your all-play matchup record. A table lists each category's rank, tier and how close the teams above and below you are. Start here: it tells you which categories a trade should target.

**Waiver wire** tries every free agent against every player on your roster and ranks the swaps by category wins gained. Free agents listed OUT are skipped, and players on IR are never suggested as drops. Each move comes with a plain-English reason, such as "+3 category wins: passes 2 teams in STL, 1 in BLK", and a button to load it into the Mock trade.

## Trade finder

Searches **every 1-for-1, 2-for-1 and 1-for-2 deal with every other team** and keeps only **win-win** ones: your category wins go up and theirs don't go down, judged by each team's own needs and punts. Those are the deals a sensible manager could say yes to.

- **Rosters stay full.** Whoever receives two players drops their least useful one. Whoever gives two picks up the best available free agent for the open spot.
- **Lopsided deals** are hidden by default. A deal is lopsided when the general value given and received differ by more than 1.5, which usually means a manager who checks the rankings will refuse.
- Below the deals: **Top targets** (players on other rosters worth the most to you) and **Trade chips** (your players worth more to others than to you).

Every deal has a **Load into mock trade** button.

## Create a trade *(new)*

Start from the player you want and work backwards.

1. **Pick the player.** Type a name into **Player you want**. The list holds every healthy player on another roster, most valuable to *your* team first, labelled with position and team. Free agents are on the Waiver wire tab, and players on IR aren't listed.
2. **Every package is built and scored.** That covers 1-for-1, 2-for-1 (you send two), 1-for-2 (you also get one of his teammates) and 2-for-2. Rosters stay full by the Trade finder's rules. Each deal is scored three ways:
   - **You:** change in your category wins.
   - **Them:** change in *their* category wins, by their own needs. This is the best guess at whether they'd say yes.
   - **Fairness:** the gap in general value, which is roughly how the deal looks to someone checking the rankings.
3. **Offers are sorted by how likely they are to be accepted:**

| Label | Meaning | Sorted by |
| --- | --- | --- |
| **Likely to work** | You gain, they don't lose, and it isn't lopsided in your favour | Your gain, then giving up the least value |
| **Costs you** | They'd likely accept, but it doesn't help your categories: the realistic *price* of the player | Cheapest first |
| **They'd likely say no** | Helps you, but costs them category wins or looks lopsided | How close they come to accepting |

You see the top 5 **Best offers**. If fewer than 3 deals are likely to work, the page also shows **What it would take** and **Good for you, harder to sell**, so you're never left with an empty page.

Each offer card shows the players, both teams' change in category wins, the value gap, a one-line reason ("passes 7 teams in 3PM, 6 in FT%; costs 5 teams in REB") and any roster fill-in moves. **Load into mock trade** takes it to the Mock trade tab to fine-tune.

**Deal sizes** filters the list. Two-player returns (1-for-2 and 2-for-2) often top the list because the *second* player adds value too. Choose 1-for-1 to see what the player alone would cost.

> **Example (real data).** Target Stephen Curry, 1-for-1 only. *Shai Gilgeous-Alexander for Curry* is **likely to work**: you +2, them +6, you give 2.8 more value. *Jalen Williams for Curry* would win you +11, but you'd get 5.2 more value than you give, so they'd likely say no.

### Offer Builder *(new, top of the Create a trade tab)*

The other way round: "I'll move these guys; what's the best I can get, and from whom?"

- **Trade block:** up to 6 of your players. A note flags anyone whose value sits mostly
  in your Lock or Punt categories; they cost you the least to deal.
- **Target team** or **Any team**, **max players you give / get** (1-3 each), and an
  **acceptance level**: *Win-win* (they don't lose category wins, not lopsided), *Close
  call* (costs them at most 2, not lopsided) or *Max gain* (no limit; lopsided deals
  flagged). *Advanced*: exclude injured players you'd receive; allow uneven deals.
- **Find offers** searches every deal up to 3-for-3 (refusing any search over 250,000
  deals before it starts) and returns up to 15, at most 3 per team when searching every
  team. Uneven deals keep both rosters full, as in the Trade finder.
- Each row expands into **why it helps you** and **the pitch**: the same numbers from
  the other manager's side, ready to send ("This helps you in AST, 3PM: you'd pass 2
  teams in AST, 1 in 3PM. You'd give up 1 team in BLK.").
- No offers? Buttons try the next acceptance level or show your top targets.

### Three-team deals *(new, bottom of the Create a trade tab)*

When the player you want sits on a team that wants nothing you have, a third team can
make it work. Three packages move around a circle: **you send to one partner, that
partner sends to the other, and the other sends to you.** Each team gives one package and
gets one, and each is scored by its own needs and punts. A deal is listed only if all
three pass.

- **Mode:** *Unlock a player* (pick the player you want; his team sends him, alone or
  with one teammate, and you pick the third team or leave it on *Any team*) or *From my
  trade block* (up to 6 of your players; *Partners* left empty means any two teams, or
  name one or two).
- **Players per package** (1 or 2) and the same **acceptance levels** as Offer Builder,
  applied to both partners. *Advanced*: skip injured teammates you'd receive (Unlock),
  or how many of each partner's most movable players to try, 4 to 8 (trade block).
- **Find three-team deals** returns up to 10, at most 2 from any pair of partners. In
  Unlock mode a line shows the best two-team deal for the same player, and a three-team
  deal is listed only if it beats it, since two trades are harder to land than one.
- **Shortcut:** when *Search by player* finds fewer than 3 deals likely to work, a **Try
  a three-team deal** button runs this search for him.

Each deal card shows your gain and whether all three teams gain, then one row per team:
what it sends, what it gets, its change in category wins and why. A partner whose side
looks lopsided is flagged.

- **How to do it on ESPN.** ESPN only trades between two teams, so a three-team deal runs
  as two trades through a *middle team*, which makes both. Any of the three can be the
  middle, and all three ways end with the same rosters. The card recommends the one where
  the middle team is least exposed if trade 2 never happens ("If trade 2 falls through,
  Team B is at +4 category wins"), and notes when the middle team needs an open roster
  spot, a trade looks lopsided on its own (a veto risk), or two review periods back to
  back would run past the trade deadline.
- **Pitches:** one for each partner, written from their side, plus **one message for
  the group** covering the whole circle and the order to run the trades. Each has a copy
  button.
- **Load into mock trade** and **Compare players** (the first 4 players).

Every recommendation on this page (Waiver wire, Trade finder, Create a trade, Offer
Builder, three-team deals) has **Load into mock trade** and **Compare players**, which opens the Compare
page's Players mode with everyone in the deal (up to 4).

## Mock trade *(updated)*

Try any deal by hand. Pick a partner, then **You send** and **You get**. Choose **Free agents** as the partner to test a pure waiver move: what you send is dropped and what you get is added.

**Your other moves** *(new)*. Two boxes under the trade, **Add free agents** and **Drop players**, take as many players as you like. Use them to test the whole plan: trade, then grab a free agent and cut someone. Options update so you can't drop a player you're already trading or add the same free agent twice. The partner's own optional add and drop sit in a collapsed section underneath.

**Roster count** *(new)* sits under the boxes. For example, "Your roster: 12 → 11 players. To stay at 12, add 1 more", or a ✓ when you're even.

**Suggest a pickup** *(new)* ranks the 5 best free agents for the roster this move leaves you:

- **A plain add** if the move opens a spot. Filling an empty spot is worth a lot, so these can all show a similar number; they're ordered by value to you.
- **An add-and-drop pair** otherwise. Suggested drops only come from players you already had, never someone you're receiving.
- Ranked by your current category strategy, including any overrides.
- **Add to move** puts the suggestion straight into the boxes.

**Step by step** *(new)*. When a trade is combined with your own moves, a small table shows category wins and matchup record at each stage, so you can see what each part contributes:

|  | Category wins | Matchup record |
| --- | --- | --- |
| Now | 66 | 10-3-0 |
| Trade only | 57 (−9) | 5-8-0 |
| Trade + your moves | 67 (+1) | 10-3-0 |

Below that, as before: every player in the deal with health and games-played history, each team's category ranks before and after, and per-game totals before and after.

**Three-team deals** *(new)*. Set **Teams in the deal** to 3 and pick two partners. Three boxes follow the circle: *You send to Partner 1*, *Partner 1 sends to Partner 2*, *Partner 2 sends to you*. **Reverse direction** sends to Partner 2 first. Partners keep their rosters full automatically (their drops and free-agent adds are listed, not editable); your own adds, drops, roster count and Suggest a pickup work as above. Results come for all three teams (one tab each), with the step-by-step table, the ESPN plan and per-game totals. Load into mock trade on a three-team card fills all of it.

## Limits and tips

- **It models category wins, not people.** "Likely to work" means the deal helps their categories and looks fair by value. Their roster loyalty, playoff plans or hunches can still say no.
- **Over-full rosters aren't charged.** If your moves leave you *over* your roster size, the extra players simply add their value, so trim back to an even count before trusting the numbers. The roster count reminds you.
- **Early season, prefer Blended or Projected.** Last-7 or last-15 stats swing wildly on a few games.
- **IR players are left out of trades and totals.** They add nothing until they're activated.
- **Three-team deals need two accepted trades.** The middle team holds players in between; if trade 2 falls through, it keeps the in-between result the card shows.
- **The trade-block search tries only each partner's most movable players** (6 by default, up to 8), so deals built around a partner's core players aren't found there. Unlock mode tries every player on the third team.
- **Use the tabs together:** Team profile to see what you need, Create a trade or Trade finder to find a deal, then Mock trade to fine-tune it with adds and drops.
