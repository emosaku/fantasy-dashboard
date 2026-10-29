# LeagueLabWhop: replacing ESPN's data

**Status: plan (October 18, 2026).** The Whop version sells software, not data: each
customer brings their own ESPN league. That covers the customer's own league data. It
doesn't cover ESPN's own content (projections, rankings, written outlooks), so that
content has to go or be replaced before we charge anyone.

This is a plan, not legal advice. The open questions are in
[product.md](product.md#questions-for-a-lawyer).

## Every ESPN field, sorted

| Data | Where it comes from | Used on | Verdict |
|---|---|---|---|
| League settings, teams, owners, rosters, lineup slots, eligibility | The customer's league | Every page | **Keep.** Their league, read with their permission |
| Matchups, weekly category results, weekly points | The customer's league | Power Rankings, Matchups & Luck, points pages | **Keep** |
| Transactions (adds, drops, trades) | The customer's league | Transactions | **Keep** |
| League point values and categories | The customer's league | Every page | **Keep** |
| Free agents list | The customer's league | Trade Analyzer, waivers | **Keep** |
| Actual stats: season, last 30/15/7 days | ESPN's player data (facts) | Compare, Trade Analyzer, Roster Strength | **Replace** with BallDontLie game stats (same 15 stats and windows, [projections.md](projections.md)) |
| Games played history (`player_seasons`) | ESPN's player data (facts) | Games projections | **Replace** with BallDontLie game stats |
| NBA schedule | ESPN (facts) | Points pages, projections | **Keep for now**, same reasoning as actual stats |
| Injury status, expected return | ESPN (reported facts) | Health, Trade Analyzer filters | **Replace** with BallDontLie's injuries endpoint |
| ESPN's fantasy points for actual stats (`appliedAverage`, source `espn`) | Arithmetic on facts | Points pages (cross-check) | **Keep**, or drop: we already compute the same numbers ourselves |
| **Projected stat line** (`projected` window in `player_stats`) | **ESPN's forecast** | Compare, Trade Analyzer, Roster Strength, Power Rankings, points pages | **Replace** with [our projections](projections.md) |
| **Projected fantasy points** (`projected` window in `player_points`) | **ESPN's forecast** | Points pages | **Replace**: our line x the league's point values |
| **Season outlook text** (`season_outlook`) | **ESPN's written analysis** | "ESPN outlook" expanders on Compare and Trade Analyzer | **Drop** |
| **ADP, auction values, draft ranks, % owned** | **ESPN's rankings and crowd data** | The Draft Tool | **Gone** with the Draft Tool ([draft-tool-removal.md](draft-tool-removal.md)) |

## Work items

1. **Drop the outlook.** Done October 21 ([projections-in-app.md](projections-in-app.md)).
2. **Swap the `projected` window** to our model's line. Done October 21.
3. **Stop storing ESPN's projected numbers at all.** Done October 21: ESPN's
   `_projected` window is no longer read.
4. **Wording.** No ESPN logos or look-alike branding; describe the product as "works
   with ESPN fantasy basketball leagues" plus a "not affiliated with ESPN" line (a
   lawyer question). Rename labels like "ESPN outlook".
5. **Actual stats, games history and injuries** from BallDontLie ALL-STAR, leaving ESPN
   as the source of league data and the NBA schedule only. Done October 29
   ([nightly-update.md](nightly-update.md)). ESPN's fantasy points for actual stats are
   dropped too: ours are stored, ESPN's are only compared in memory.

## Public and private leagues

Private ESPN leagues need the member's `espn_s2`/`SWID` cookies, which work like their
ESPN password. League Lab can store them (`app/espn_login.py`, secrets named
`league-*`), but holding paying customers' ESPN logins raises the security and
liability bar. **Recommendation: launch with public leagues only** (the commissioner
turns on "viewable to public" in ESPN, as League Lab already asks) and add private
leagues later as a deliberate decision.

## The risk that stays

ESPN's API is unofficial: it can change or block us without notice, and ESPN's terms
don't welcome automated access in any case. Bringing your own league reduces the
licensing risk; it doesn't remove the reliability risk. Keep `scripts/teardown.py`
working, and keep the per-league ESPN load light (the Draft Tool's removal already cut
one view and a 400-player pull per league).
