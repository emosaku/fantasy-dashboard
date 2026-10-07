# League Lab metrics: z-scores and everything built on them

*This guide covers categories leagues. For points leagues, see
[points-guide.md](points-guide.md).*

*Last updated October 6, 2026. League Lab version: every metric works with each league's
own categories and scoring. The single-league site's version is on `main`
(`docs/metrics.md`).*

The dashboard turns box scores into a handful of numbers. This doc explains each one,
how it's computed, and where it shows up. Most of them build on one idea, the
**z-score**, so that comes first.

Everything is computed **per league**: each league's categories, scoring type, teams and
player pool come from ESPN when the league is registered, and are refreshed with every
data load. The SQL views compute the metrics; after each load they're copied into
per-league `m_*` tables, which are all the dashboard reads.

| Metric | One-line meaning | Where it's used |
| --- | --- | --- |
| [Player z-score](#1-player-z-score) | How far above or below a typical player he is in one category | Everything below |
| [Team z total](#2-team-z-total) | Sum of a team's healthy players' z-scores in a category | Category Rankings (roster), Trade Analyzer |
| [Roster Strength z](#3-roster-strength-z) | How a team's combined per-game stats compare with other teams | Roster Strength heatmap |
| [Category ranks](#4-category-ranks) | Each team's rank per category, by roster or by results | Roster Strength → Category Rankings |
| [All-play record](#5-all-play-record-and-power-rankings) | Your record if you'd played every team every week | Power Rankings |
| [Luck](#6-luck) | Actual win % minus all-play win % | Matchups and Luck |
| [Category wins (E)](#7-category-wins-e) | Categories you'd win against every other team | Trade Analyzer: every tab, incl. Offer Builder and Mock trade's step by step |
| [Tiers and weights](#8-tiers-and-weights) | Which categories are worth fighting for | Trade Analyzer, Offer Builder's block notes, Compare's fit row |
| [Value to you / general value](#9-value-to-you-and-general-value) | A player's worth to your team / to anyone | Trade Analyzer (incl. the lopsided check), Compare's fit row |
| [Empty roster spot](#10-empty-roster-spot) | The z of a roster spot with nobody in it | Mock trade, Suggest a pickup, step by step |
| [Player rankings](#11-player-rankings) | Every player ranked per category and overall | Player Rankings, Compare's stat table |
| [Projected finish](#12-projected-finish) | Injury-aware all-play record through the end of the season | Power Rankings |
| [Season totals](#13-season-totals) | Per-game stats × games played, ranked among the pool | Compare (Season totals) |
| [Position baseline](#14-position-baseline) | The average starting PG/SG/SF/PF/C | Compare (Compare against) |
| [Verdicts, deal labels and pitches](#15-verdicts-deal-labels-and-pitches) | One-line judgments built from the numbers above | Compare, Create a trade, Offer Builder |

Throughout, **K** is the number of categories the league scores and **N** the number of
teams.

---

## 0. Categories, as data

Each ESPN scoring item maps to a category of one of two kinds (`ingest/catalog.py`):

| Kind | Examples | How a team's number is formed |
| --- | --- | --- |
| **Count** | PTS, REB, AST, STL, BLK, 3PM, TO, FGM, FTM, OREB, DREB… | Sum of per-game averages |
| **Ratio** | FG%, FT%, 3PT%, A/TO | Recomputed from the two totals (e.g. makes ÷ attempts), **never averaged**: 1-for-1 plus 40-for-100 is 41/101 = 40.6%, not 70% |

ESPN also marks **lower-is-better** categories (turnovers). Every metric below compares a
**score** that flips those, so **higher is always better** everywhere: fewer turnovers
means a higher score, a positive z, a better rank.

Categories without ESPN per-game averages (double-doubles, triple-doubles) can't be
computed, so leagues that score them are refused at registration.

## 1. Player z-score

**What it is.** For one player in one category: how many *standard deviations* he sits
above (+) or below (−) the average player in his league's pool.

```
z = (player's score − pool average score) ÷ pool spread
```

- **0** is an average pool player; **+1** is clearly above average; **+3** is elite;
  negative numbers are below average. A positive z is always good, including in
  lower-is-better categories.
- Because every category is put on the same scale, z-scores can be **added across
  categories and across players**. That's the whole point: "2.0 steals" and "33 points"
  aren't comparable, but "+3.2 in steals" and "+3.1 in points" are.

**Worked example (real data, projected stats, the test league).** The pool averages
14.9 points a game with a spread of 5.8. Luka Dončić is projected at 33.0:
`(33.0 − 14.9) ÷ 5.8 ≈ +3.1`. In steals, the pool averages 0.96 with a spread of 0.32,
so a 2.0-steal player is `(2.0 − 0.96) ÷ 0.32 ≈ +3.3`: steals are scarcer, so the
same "good" number is worth more.

**The pool.** Averages and spreads are taken over each league's **rostered players plus
its top 100 free agents** (`FREE_AGENT_COUNT`; about 255 players in a 14-team league).
Including free agents matters: the scale then reflects who's realistically available,
and waiver pickups are scored on the same scale as rostered players. Spreads are
population standard deviations. Each league has its own pool, so the same player can
have slightly different z-scores in different leagues.

**Count categories** use the per-game value as the score (a missing stat counts as 0).
For a **lower-is-better** count, the score is its negative: a player averaging 1.0
turnovers in a pool averaging 2.0 gets a *positive* z.

**Ratio categories** can't be used directly: a 2-for-2 shooter would look like the best
in the league. Instead the score is the **impact**, the extra numerator a player adds
compared with a league-average player on the same volume:

```
impact = numerator − league rate × denominator
       = (player's ratio − league rate) × denominator
```

where *league rate* is pooled across the league's pool (total makes ÷ total attempts,
total assists ÷ total turnovers, and so on). A 55% shooter on 15 shots a game against a
48% league rate has impact `(0.55 − 0.48) × 15 = +1.05` made shots a game: much more
valuable than a 70% shooter on 2 shots (`+0.44`). A player with a zero denominator has
impact 0. Because the league rate is pooled, impacts average out to exactly 0 across
the pool.

**Stat windows.** Every z-score exists per window: *projected* (ESPN's projection),
*season*, *last 7 / 15 / 30 days*, and **blended**, which mixes season and projected by
games played:

```
blended z = α × season z + (1 − α) × projected z,   α = min(season games ÷ 20, 1)
```

All projection before a player's first game, all real stats from game 20 on. A player
with only one of the two windows uses it alone.

**Where:** `sql/views/07_v_player_z.sql` → `m_player_z`; read by the Trade Analyzer,
Player Rankings and Category Rankings.

## 2. Team z total

**What it is.** A team's strength in a category: the **sum of its players' z-scores**,
leaving out players in an IR slot (they aren't playing).

A team at +6.0 in assists has, in total, six standard deviations of assists above six
average players. Totals are only compared *between teams*, so the absolute number
matters less than the gaps.

**Where:** `sql/views/08_v_team_category_z.sql` (Category Rankings, roster lens) and
`app/analysis/pool.py` (the Trade Analyzer re-totals them for every simulated move;
the two always agree).

## 3. Roster Strength z

A **different** z-score, at team level, used by the Roster Strength heatmap
(`sql/views/11_v_roster_strength.sql`):

1. Combine each roster's per-game output (IR excluded): count categories summed, ratios
   recomputed from the summed totals.
2. Z-score each category **across the league's teams**, lower-is-better flipped: how
   many standard deviations a team sits above or below the league's average *team*.

So a cell of +1.5 in REB means "this roster rebounds 1.5 spreads more than the average
roster in this league." It answers *how teams compare*, while the team z total
(section 2) answers *how much player value a roster holds*. They usually agree on order
but not on size. Raw stat windows only: blended has no raw totals.

## 4. Category ranks

Every team ranked **1 to N in every category of its league** (1 is best; ties share a
rank), through two lenses (`sql/views/09_v_category_ranks.sql`):

| Lens | Based on | Use it for |
| --- | --- | --- |
| **Roster** | Team z totals (section 2), per stat window | Forward-looking: how good the roster is. Works before games start |
| **Results** | Finished weeks only | What actually happened |

Ranks use the flipped score, so the fewest turnovers ranks first; the table still shows
the real value. In the results lens, count categories are the average weekly value,
ratios pool their two totals over those weeks, and **win rate** is the share of other
teams beaten in that category (ties half), averaged over weeks.

**Gap above / gap below** is the distance to the next-better / next-worse team, which
shows how secure a rank is. These ranks and gaps feed the tiers in section 8.

## 5. All-play record and Power Rankings

**What it is.** Your record if you'd played **every other team every week** instead of
one opponent (`sql/views/02_v_all_play.sql`).

Each week, every team is compared with each of the other N − 1 on the league's
categories, using the flipped score so lower-is-better categories count correctly. A
ratio with a zero denominator can't be compared and counts as a tied category. That
gives two records:

- **Matchup record**: against each opponent, whoever wins more categories gets the W.
  Up to N − 1 results a week.
- **Category record**: every single category result. Up to K × (N − 1) a week.

**Power Rankings** rank on the measure the league's own scoring uses
(`sql/views/03_v_power_rankings.sql`):

| League scoring | Ranked on |
| --- | --- |
| **Most Categories** (a week is one W/L/T) | Season-to-date all-play **matchup** win % |
| **Each Category** (a week is a category record, e.g. 6-3-0) | Season-to-date all-play **category** win % |

Ties count as half a win. A team's rank reflects how good it was every week, not who it
happened to draw.

## 6. Luck

```
luck = actual win % − all-play win %
```

Positive means **lucky** (winning more than the team's stats deserve), negative means
**unlucky** (`sql/views/04_v_luck.sql`). It's measured **at the level the league scores**:

- **Most Categories:** a week's W/L/T against all-play matchup win %.
- **Each Category:** a week's category record (e.g. 6-3-0) against all-play category
  win %.

Actual results are ESPN's own per-category verdicts. Example (Most Categories): a narrow
win in a week when the team would have beaten only 3 of 13 teams is
`1.0 − 3/13 ≈ +0.77` of luck for that week. The chart shows the running season total.

## 7. Category wins (E)

**What it is.** The Trade Analyzer's scoreboard: how many categories a team would win
if it played every other team at once, using team z totals (section 2):

```
E = Σ over categories, Σ over opponents of: 1 if ahead, 0.5 if tied, 0 if behind
```

The most is **K × (N − 1)**: for example 9 × 13 = 117 in a 14-team, 9-category league.
A move is judged by how much it changes E; "+3 category wins" means the team now beats
three more opponent-category pairs (for example it passes 2 teams in AST and 1 in STL).
The plain-English explanations under each deal are this breakdown. E fits both scoring
types, since both are decided category by category.

- **Punted categories are left out of your own E** (section 8), so the analyzer never
  rewards gains in a category you've given up.
- The **all-play matchup record from totals** (e.g. 10-3-0) is shown next to E. Every
  category counts there, punted or not, because a real matchup counts them all.

**Where it's used:**

- **Waiver wire, Trade finder:** each move's change in your E, explained category by
  category.
- **Create a trade and Offer Builder:** two changes per deal: **ΔE you** and **ΔE
  them**, the partner's change judged by *their* own tiers and punts. Every Offer
  Builder result has ΔE you > 0; its acceptance level then filters on ΔE them (see
  section 15).
- **Mock trade's step by step:** E and matchup record at *Now*, *Trade only* and
  *Trade + your moves*, so you can see what the trade and your own adds/drops each
  contribute.

**Where:** `app/analysis/objective.py` (E), `app/analysis/trades.py` (deal scoring).

## 8. Tiers and weights

**What it is.** For your team, how much each category is worth fighting for, based on
how close the races around you are (`app/analysis/weights.py`).

Pick a **swing size δ** (default 1.0 z, about one solid starter: the "Swing size"
control). For each category, look at the gaps between your team total and everyone
else's:

- **U (up)**: opponents just ahead of you, within δ. A realistic gain would pass them.
- **D (down)**: opponents just behind you, within δ. A realistic loss would let them
  pass you.

```
raw weight = (U + 0.5 × D) ÷ (N − 1)
```

Gains count fully and losses half, because the analyzer is looking for upgrades. The K
weights are then scaled to sum to K (average 1.0).

**Tiers:**

| Tier | Rule | Weight |
| --- | --- | --- |
| **Lock** | Ranked top 3 and nobody within δ behind you (D = 0) | From the formula, usually low |
| **Punt** | Ranked in the last 3, whatever the league size, and nobody within δ ahead (U = 0) | 0: left out of E and values |
| **Swing** | Everything else | From the formula |

The **Category strategy** overrides replace a category's raw weight with Lock 0.5,
Swing 1.5 or Punt 0 before scaling. If nothing is within reach anywhere, every
non-punted category gets weight 1.

**Where tiers show up beyond the Trade Analyzer's scoring:**

- **Offer Builder's trade block:** a player whose positive z-scores sit mostly in your
  *Punt* or *Lock* categories is noted ("value mostly in your Punt categories"): he
  costs you the least to trade.
- **Compare's fit row:** "70% of his value is in your Swing categories" -- each
  player's weighted value (section 9) split by the tier each category is in, counting
  only categories where he adds positive value.

## 9. Value to you and general value

Two ways to put one number on a player (`app/analysis/weights.py`):

```
value to you  = Σ (player's z × your weight)      over the league's categories
general value = Σ  player's z                       (no weights)
```

- **Value to you** prices a player for *your* needs: a big shot-blocker is worth a lot
  if blocks is a Swing category for you, and nothing if you punt blocks. It sorts *Top
  targets*, the *Create a trade* player list, *Trade chips* and waiver tie-breaks.
- **General value** is the same for every team and close to how ESPN's rankings see a
  player. It's the **fairness check**: a deal is **lopsided** when the general value
  given and received differ by more than **1.5**, because a manager who checks the
  rankings will likely refuse it. *Create a trade* uses it to label deals *They'd
  likely say no*; Offer Builder drops lopsided deals under *Win-win* and *Close call*
  and flags them under *Max gain*.
- **Compare's "Fit for your team"** shows both side by side for each player (and for a
  position baseline), so two players with similar overall ranks can be told apart by
  how much they help *your* roster. It uses the same weights as the Trade Analyzer, so
  the numbers match.

## 10. Empty roster spot

z = 0 is an *average* player, not an *empty* spot. When a move leaves a team a player
short (a 2-for-1, or dropping without adding), the open spot is scored as **a player
with no stats**: a score of 0 in every category (`app/analysis/pool.py`,
`empty_slot_z`):

```
z_empty = (0 − pool average score) ÷ pool spread
```

which works out as:

| Category kind | Empty spot | Why |
| --- | --- | --- |
| Count, higher is better (PTS, REB…) | Clearly negative | Contributes nothing |
| Count, lower is better (TO) | Positive | Commits no turnovers |
| Ratio (FG%, FT%, 3PT%, A/TO) | 0 | No volume, so it doesn't move the team's ratio |

On the test league's projected data that's about −2.6 in PTS, −2.2 in REB, −1.8 in AST,
−3.0 in STL, −1.3 in BLK, −1.6 in 3PM, and 0 in the three percentages. The calculation
reproduces the stored z-scores exactly, so it's on the same scale. For the blended
window it's the average of the season and projected values.

Without it, an open spot would count as an average player: 2-for-1 deals would look
better than they are and every pickup into an open spot would look worthless.

## 11. Player rankings

Every pool player is ranked in each category by z-score (1 is best, ties share a rank),
and **overall by total z** (the sum across the league's categories, which is the same as
general value) (`app/analysis/rankings.py`). Ranks are league-wide: among rostered
players and the top free agents together.

**Compare's stat table** shows the same ranks beside each value (they're computed from
the whole pool, not just the players being compared, so they always match Player
Rankings), and its *Overall rank* footer is the same overall rank. A position baseline's
rank is where its average z would land among the pool.

## 12. Projected finish

Power Rankings' *Projected finish* (`app/analysis/projection.py`) keeps the real
all-play record for finished weeks and projects every remaining week from today's
rosters:

- Each player contributes his per-game line (season averages once he has them, else
  ESPN's projection), **only in weeks he's expected to be available**.
- Injured players return on ESPN's expected date when it has one; otherwise by status:
  IR slot misses 4 weeks, OUT 2, day-to-day 1. All adjustable on the page.
- Team lines are combined (ratios recomputed from their totals, lower-is-better
  flipped), and every team plays every other team in each projected week, as in
  section 5. A projected week counts as a matchup W/L/T in Most Categories leagues and
  as a category record in Each Category leagues.

It sums every available rostered player rather than a real starting lineup, so it
doesn't model a manager moving a bench player into an injured starter's spot.

## 13. Season totals

Compare's **Show: Season totals** turns per-game numbers into a season's worth, so games
played count (`compare.py`, `season_totals`):

```
count categories:  total = per-game stat × games played
ratio categories:  season numerator ÷ season denominator   (each = per-game value × games)
```

Games played is the stat window's own: **projected games** for *Projected*, games so far
for *Season*. For *Blended* (which has no raw stat line of its own) a player's season
line is used once he has one, otherwise his projection.

Totals are **ranked among every pool player's totals**, not converted to z-scores. A
count ranks by the total itself, flipped for a lower-is-better category, so 80 season
turnovers outrank 200. A ratio ranks by its season **impact**, the extra made over a
league-average player on the same season volume:

```
impact = season numerator − league rate × season denominator      (league rate pooled over the pool)
```

so 600 attempts at 52% can outrank 100 attempts at 60%. In totals mode the verdict and the
bold "best" cell use the same total or impact. The charts and the fit row stay per game
(they're built on per-game z-scores), and the page says so.

## 14. Position baseline

Compare's **Compare against: average starting PG/SG/SF/PF/C** (`compare.py`,
`position_baseline`). The members are every **rostered** player at that position in an
**active lineup slot** (not bench, not IR) in the chosen stat window. The baseline is a
full row on the page:

| Field | How it's built |
| --- | --- |
| z per category | The members' average z |
| Count value | The members' average per-game stat |
| Ratio | **Pooled**: all members' numerators ÷ all members' denominators (never an average of ratios); the two totals shown are the members' averages |
| Rank | Where that average z would land among the whole pool |
| Season totals | The members' average totals (ratios pooled again) |
| Fit for your team | The average z run through your weights, like any player |
| Recent form | The baseline recomputed in each window |
| Durability | The members' average games over the last 3 seasons |

## 15. Verdicts, deal labels and pitches

Several one-line judgments are counted straight from the numbers above, never written
by a model:

- **Compare's head-to-head verdict** (exactly two entries): "A wins 6 of 9 categories;
  B is better in FT%, 3PT% and STL." It counts category wins by **z** (per game) or by
  **season total / impact** (totals mode), so ratios are judged with volume and fewer
  wins a lower-is-better category. Equal values are ties and favor neither side.
- **Create a trade's labels** (one target player): *Likely to work* (ΔE you > 0, ΔE them
  ≥ 0, not lopsided in your favor), *Costs you* (they'd accept, but ΔE you ≤ 0: the
  player's realistic price), *They'd likely say no* (helps you, but costs them or looks
  lopsided).
- **Offer Builder's acceptance levels** (a filter you pick; every result has ΔE you > 0):

  | Level | Rule |
  | --- | --- |
  | Win-win | ΔE them ≥ 0 and not lopsided |
  | Close call | ΔE them ≥ −2 and not lopsided |
  | Max gain | no limit on ΔE them; lopsided deals shown and flagged |

  Results are ranked by ΔE you, then ΔE them, with near-duplicates dropped (a deal that
  only adds a throw-in with no extra gain). Uneven deals keep both rosters full: the side
  that ends up with extra players drops its lowest-value ones, and the side left short
  picks up that many of the best free agents, each by its own weights.
- **Offer Builder's pitch:** the *partner's* per-category change, phrased for them to
  read: "This helps you in AST, 3PM: you'd pass 2 teams in AST, 1 in 3PM. You'd give up
  1 team in BLK."

---

## Things to keep in mind

- **z-scores are relative to each league's pool.** If the pool changes (new free agents,
  a different stat window), the same stat line can get a slightly different z, and the
  same player can differ slightly between leagues.
- **Ratios are about volume as much as accuracy.** A high-volume, slightly above-average
  shooter often beats a low-volume, very accurate one, which matches how percentages
  actually move in a weekly matchup.
- **Higher is always better in the score.** Lower-is-better categories are flipped
  once, at the source, so every page, rank and trade can treat all categories alike.
- **Early in the season, small windows are noisy.** Last-7 and last-15 z-scores can
  swing on two or three games; *blended* or *projected* is steadier.
- **IR players are excluded** from team totals, trades and projections until they're
  activated.
