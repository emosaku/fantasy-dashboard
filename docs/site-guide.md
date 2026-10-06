# League dashboard: a guide to every page

*Last updated October 6, 2026.*

## Overview

The league dashboard shows everything ESPN doesn't for our 14-team, 9-category head-to-head league (FG%, FT%, 3PM, 3PT%, REB, AST, STL, BLK, PTS; no turnovers). It has eight pages: **Home**, **Compare**, **Power Rankings**, **Matchups and Luck**, **Transactions**, **Roster Strength**, **Trade Analyzer** and **Player Rankings**.

**Signing in.** Each manager has their own username (`first.last`) and password from the commissioner. You stay signed in on that device for 30 days. Five wrong passwords lock a username for 15 minutes. Once you're signed in, your team is the default everywhere, and the Trade Analyzer gives recommendations for your own team only (the commissioner can pick any team). The sidebar shows who's signed in, with a **Log out** button.

**How fresh the data is.** Data is pulled from ESPN every morning at 5 AM Arizona time. The sidebar on every page shows when it last updated. **Refresh data** pulls from ESPN on demand, for example right after a trade. It takes about a minute and can be pressed again 10 minutes after the last update.

**How the pages fit together**

| If you want to know... | Go to |
| --- | --- |
| Who's actually the best team, ignoring schedule luck | Power Rankings |
| How this week's matchups went, and who's been lucky | Matchups and Luck |
| Who did what on the wire or in trades | Transactions |
| Where your roster is strong or weak, category by category | Roster Strength |
| How two teams, or two to four players, stack up | Compare |
| Which pickups and trades would help you most | Trade Analyzer |
| Where any player ranks, rostered or free agent | Player Rankings |

The pages share one foundation: every player's **z-score** in each category, meaning how far above or below a typical player he is. That's why a player's rank, value and trade impact agree from page to page. [metrics.md](metrics.md) explains every number in detail.

## Home

The landing page: league **standings** (rank, team, record and each manager's real name) and a link to every page, with a one-line description of each.

## Compare

Compare has two modes, picked with the **Teams | Players** toggle at the top. Each mode remembers its own selections when you switch back and forth.

### Teams mode

Pick a **Team** (yours by default), an opponent (**Against**) and a **Period**: the whole **Season** or any single week.

- **Verdict:** one line saying who would win if the two played in that period, e.g. "would beat X, winning 6, losing 2 and tying 1 of the 9 categories."
- **Category profile:** a radar chart of each team's z-score per category. The dotted ring is the league average.
- **By category:** nine small bar charts of the raw numbers. Each bar is labelled, and bars start at zero so small percentage gaps look as small as they are.
- **Table view:** the same numbers as a table.

Season mode averages counting stats per week and pools makes and attempts for percentages, so a 1-for-1 night doesn't count like a 10-for-20 one.

### Players mode

Compare **2 to 4 players**, rostered or free agent, or one player against a typical starter.

**Controls**

- **Stats from:** which numbers to judge on (Blended, Projected, Season, Last 7/15/30).
- **Filter picker by:** chips for *My team*, *Other teams* and *Free agents* that narrow the player list.
- **Players:** a searchable list. Each entry shows name, position, team (or FA) and a health badge. Up to 4.
- **Compare against:** an optional **average starting PG, SG, SF, PF or C**. It's the average of every rostered player at that position in an active lineup slot (not bench or IR), so one player can be measured against a typical starter.
- **Show:** **Per game** or **Season totals**. Totals multiply per-game stats by games played in that stat window (projected games for Projected), so a player who plays 70 games counts for more than one who plays 40.

**What it shows**

1. **Verdict** (with exactly two entries): "Player A wins 6 of 9 categories; Player B is better in FT%, 3PT% and STL." It's judged on z-scores, or season totals when that's selected, so percentages count volume.
2. **Category profile:** a **radar**, or grouped **bars** (the default on a phone, switchable). Values are clipped to ±3 so one outlier doesn't flatten the chart; hover shows the true number. Each player keeps one color and line style on every chart, and the baseline is gray.
3. **Stat table:** one row per category with the value, league rank, and makes/attempts beside a percentage ("52.2% on 8.4 FGA"). The best in each row is **bold**. Footer rows show overall rank, total z and games played.
4. **Fit for your team:** each player's *value to you* (weighted by your Lock/Swing/Punt tiers), his general value, and where his value sits ("70% of his value is in your Swing categories").
5. **Recent form:** total z across Last 30, Last 15, Last 7 and Season as a line chart, once there's history.
6. **Health and durability:** ESPN status and return date, average games over the last 3 seasons, games in each season, and ESPN's outlook.

You can open Players mode already loaded from **Player Rankings** (*Compare selected*) or any **Trade Analyzer** recommendation (*Compare players*).

## Power Rankings

Ranks teams by **all-play**: your record if you'd played every other team every week, not just the one opponent you drew. It's the fairest measure of who's actually good.

- **Week slider** (once two or more weeks have been played): see the rankings as of any week.
- **Rankings table:** rank, all-play record and win %, category win %, and movement since last week. Teams level on win % share a rank.
- **Projected finish, as of today:** each team's real all-play results so far, plus every remaining week projected from today's rosters. Injured players are left out of the weeks they're expected to miss: ESPN's return date when it has one, otherwise 4 weeks for IR, 2 for Out and 1 for day-to-day. You can change those in **Injury assumptions**, and **Who's missing** lists every injured player and the weeks they'll miss.
- **Rank over time:** a line chart of each team's rank by week, with up to 3 teams highlighted and the rest in gray.

## Matchups and Luck

- **Week picker** and a **scoreboard** card for every matchup: the winner, and all 9 categories with the higher value in bold. Category scores are ESPN's own, so they match ESPN's matchup page.
- **Luck:** your actual win % minus your all-play win %. Positive means *lucky* (winning more than your stats deserve), negative means *unlucky*. A bar chart and table show it for the season to date, since one week's luck is mostly noise. Example: a narrow win in a week you'd have beaten only 3 of 13 teams is about +0.77 of luck for that week.

## Transactions

Every add, drop, trade and lineup move this season, including ones ESPN's own pages don't keep.

- **One filter bar** for dates, teams, action type and players. It filters the chart and the log together.
- **Activity per team:** a stacked bar chart of each team's adds, drops, trades and lineup moves, with counts.
- **Activity log:** every matching move. Lineup moves show the slots involved.

## Roster Strength

How each roster stacks up, category by category. It has two tabs.

**Category rankings**

- **Lens:** *Roster strength* (forward-looking: the sum of each team's healthy players' z-scores, which works before games start) or *Results* (what actually happened in finished weeks, with a win rate per category).
- **Stats from**, a **highlighted team** (yours by default), and a **sort** order.
- **Rankings grid:** every team ranked 1-14 in every category, plus an average rank, shaded blue (1st) to red (14th). Your team is outlined and its **Lock / Swing / Punt** tiers are shown: categories you've locked up, the close races, and ones too far behind to chase.
- **Category detail:** a bar chart of one category that shows the actual gaps ranks hide (2nd and 3rd can be miles apart or nearly tied).

**Per-game totals**

- A **stat window** (Last 7/15/30 days, or projected before games start) and a **heatmap** of each team's combined per-game output against the league average. Blue is above average and red is below. A table view is available.

## Trade Analyzer

Recommends moves for your team, ranked by how much each raises your **category wins (E)**: the categories you'd win if you played every other team at once, out of 9 × 13 = 117.

**Controls at the top** (they apply to every tab):

- **Team:** locked to yours (the commissioner can pick any).
- **Stats from:** which numbers to judge players on (Blended mixes ESPN's projection with real stats as games are played).
- **Swing size δ:** how big a realistic gain in one category is (1.0 is about one solid starter). It decides which races count as close.
- **Category strategy:** override any category to Lock, Swing or Punt. Punted categories stop counting for you everywhere.

### Team profile

Each category's rank, team z, the gap to the teams above and below, its weight and tier, plus your E (out of 117) and all-play matchup record. Start here: it tells you what to target.

### Waiver wire

The top 10 *add this free agent, drop that player* moves, ranked by category wins gained. Free agents listed OUT are skipped and IR players are never suggested as drops. Each move comes with a plain-English reason ("+3 category wins: passes 2 teams in STL, 1 in BLK").

### Trade finder

Every 1-for-1, 2-for-1 and 1-for-2 deal with every team, keeping only **win-win** ones (your E goes up, theirs doesn't go down). Rosters stay full: whoever receives two drops their least useful player, and whoever gives two picks up the best free agent. Lopsided deals (general value differs by more than 1.5) are hidden by default. Below the deals: **Top targets** (players on other rosters worth the most to you) and **Trade chips** (your players worth more to others than to you).

### Create a trade

Two ways to build a deal.

**Offer Builder:** "I'll move these guys; what's the best I can get?"

- Pick a **trade block** of up to 6 of your players. A note flags anyone whose value sits mostly in a category you've locked or punted; they cost you least to deal.
- Choose a **target team** or **Any team**, the **max players you give and get** (up to 3 each), and an **acceptance level**:
  - *Win-win*: they don't lose category wins, and the deal isn't lopsided.
  - *Close call*: costs them up to 2 category wins but looks fair on paper.
  - *Max gain*: no limit. Lopsided deals are flagged; expect most to be turned down.
- *Advanced*: exclude injured players you'd receive, and allow uneven deals (like 3-for-1).
- Press **Find offers**. Up to 15 offers come back (at most 3 per team when searching every team) in a table, with your change and theirs, your biggest category gains and losses, and any roster fill-ins. Expand a row for **why it helps you** and **the pitch**: the same numbers written from the other manager's side, ready to send.
- If nothing qualifies, buttons let you try the next acceptance level or show your top targets.

**Search by player:** type a player on another roster. Every 1-for-1, 2-for-1, 1-for-2 and 2-for-2 deal that brings him over is labelled *Likely to work*, *Costs you* (the realistic price) or *They'd likely say no*, with a deal-size filter.

### Mock trade

Try any deal by hand, or load one from another tab. Pick a partner (or **Free agents** for a pure waiver move), then **You send** and **You get**.

- **Your other moves:** add any number of free agents and drop any number of your players around the trade. The partner's own adds and drops are in a collapsed section.
- **Roster count:** e.g. "12 → 11 players. To stay at 12, add 1 more."
- **Suggest a pickup:** the 5 best free agents for the roster the move leaves you, with an **Add to move** button.
- **Step by step:** category wins and matchup record at *Now*, *Trade only* and *Trade + your moves*.
- For every player involved: health, games played over the last 3 seasons and per-game stats. For both teams: E and record before and after, ranks and tiers by category, and per-game totals before and after.

An empty roster spot counts as a player with no stats, not an average one, so a 2-for-1 is never a free upgrade.

Every recommendation row has **Load into mock trade** (same numbers there) and **Compare players** (opens Compare with everyone in the deal).

## Player Rankings

Every player in the pool (all rostered players plus the top 100 free agents) ranked in each category and overall.

- **Stats from:** the stat window.
- **Players:** all, your team, free agents, or any one team.
- **Show:** *Ranks*, *Per game* values, or *Z-scores*. Cells are always shaded by rank, blue for 1st through red for last.
- **Find a player** by name, filter by **Positions**, or **Hide injured**.
- Ranks are league-wide, so filtering to one team still shows where its players stand overall. *Overall* adds up a player's 9 z-scores. Columns sort, and the player's name stays pinned when you swipe sideways on a phone.
- **Compare selected:** tick 2 to 4 rows and press it to open them in Compare's Players mode.

## How the pages link

| From | Button | Goes to |
| --- | --- | --- |
| Player Rankings | Compare selected | Compare (Players mode, those players loaded) |
| Trade Analyzer, any recommendation | Compare players | Compare (Players mode, everyone in the deal, up to 4) |
| Trade Analyzer, any recommendation | Load into mock trade | Mock trade tab, with matching numbers |
| Home | Page links | Every page |

## Tips, limits and where the numbers come from

- **Early in the season, use Blended or Projected.** Last-7 or Last-15 stats swing on two or three games. Blended moves from ESPN's projection to real stats over a player's first 20 games.
- **Percentages are judged with volume.** A 55% shooter on 15 shots helps a team more than a 70% shooter on 2, so rankings, bolding and verdicts follow volume-weighted z-scores, not the raw percentage.
- **IR players count for nothing** in team totals, trades and projections until they're activated.
- **Recommendations model category wins, not people.** "Likely to work" means a deal helps the other team's categories and looks fair by player value; their manager can still say no.
- **Phones:** charts resize to the screen, Compare defaults to bars instead of the radar, and wide tables keep the player's name pinned.
- **Where the numbers come from:** ESPN, pulled every morning into BigQuery. Every metric (z-scores, category wins, tiers and weights, player value, luck, the projection, season totals, position baselines) is explained in [metrics.md](metrics.md). The Trade Analyzer has its own guide in [trade-analyzer.md](trade-analyzer.md).
