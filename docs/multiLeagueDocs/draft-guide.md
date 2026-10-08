# League Lab Draft Tool: how it works

*October 7, 2026. Branch `DraftTool`. Points drafts; categories next.*

The Draft page suggests your best pick at every turn: the player that leaves **your
finished team strongest against the finished teams around it**. As the draft goes, it
tracks every team's roster and plays out everyone's remaining picks, so each suggestion
is judged against what the competition is actually building.

It isn't tied to any league. It's a mock draft anyone signed in can run at any time:
before a league is on League Lab (leagues are registered after their drafts), or with
no league at all.

## Setting up a draft

Pick the number of teams, the rounds and your draft position. **Lineup and point values**
holds the starting slots, bench spots and each stat's points, with ESPN's defaults filled
in (PG, SG, SF, PF, C, G, F, 3 UT and 3 bench; PTS +1, 3PM +1, FGM +2, FGA −1, FTM +1,
FTA −1, REB +1, AST +2, STL +4, BLK +4, TO −2). Change them to match your league.

- **Players and the NBA schedule** come from ESPN's league-independent data, refreshed
  daily: the 400 best players by ESPN's points draft rank, with ADP, ESPN's ranks,
  projected stats and games, and eligible slots.
- **Fantasy points** are each player's projected stats × your point values, so bonus
  stats such as double-doubles aren't counted.
- **Injury history** is League Lab's games-played history over the last 3 seasons, or
  last season's games for a player it hasn't seen.

## Your drafts are saved

Every pick is saved to your account as you go: leave mid-draft and pick up where you
left off, on any device you're signed in on. Each setup keeps its own draft (change the
settings and you start a fresh one; change them back and your draft is there). When a
draft ends, **Start a new draft** clears it; **Start over** does the same any time.

## On the page

- **Top strip:** the pick on the clock, and "You're on the clock" or "You pick in 6
  (#40)".
- **Enter a pick:** type a few letters of the name and press Enter. If one player
  matches, he's drafted for the team on the clock; otherwise pick from the buttons.
  Typos are fine ("jokci"). **Undo** takes back the last pick.
- **Your best picks:** five cards, each with:
  - expected wins a week once every roster is full, and the gap to the next best pick
    (flagged when it's within the simulations' noise);
  - your projected rank among the finished teams;
  - FP/G, projected games and season points above replacement;
  - the chance he lasts to your next pick (or is there at your pick, when it isn't
    your turn yet);
  - the empty starting slots he fills;
  - the team most likely to take him if you pass;
  - who you'd likely take next.
- **Board:** every pick, rounds by teams, your column marked.
- **Available:** everyone left, by value, with ADP, ESPN's rank and the chance he's
  there at your pick; search and slot filters, and a Draft button.
- **League:** every team's strength now and finished (projected), expected wins,
  projected rank, and how often its roster projects strongest; any team's roster.
- **My team:** your finished projection against the league average and the leader,
  and the starting slots you haven't filled.

**Settings:** *Injury risk* (Ignore: ESPN's projected games; Neutral: capped by his last
3 seasons' average; Avoid: capped, and 15% fewer for players who average under 60 games
or are OUT) and *Simulations* (100, 200 or 400 a suggestion).

## Who makes the other picks

- **Bots make them** (a mock draft): the other seats draft like real managers (below).
  They pick up to your turn on their own; *Bots pick right away* turns that off, and
  *Bots pick to my turn* runs them by hand. **Undo** takes back your last pick and the
  bots' picks after it.
- **I enter each one** (following a real draft elsewhere): type every pick as it
  happens. *Picking for another team* covers traded picks, *Paste picks* catches up from
  text copied out of a draft room, and *Follow along* re-reads the draft every 3 seconds
  for a second screen. This draft is saved separately from your mock draft.

## How a pick is scored

For each candidate, the rest of the draft is played out 200 times:

1. **The other managers** each draft from their own board: ESPN's average draft position
   blended with ESPN's rank for the league's format (3/4 ADP, 1/4 rank), plus personal
   noise (3 picks + 20% of the spot). They take at most 6 players at one position and,
   once their picks run short, fill their empty starting slots first.
2. **You** take the candidate at your pick (if he's still there) and then draft by value
   under the same roster rules.
3. **When every roster is full,** each team's projected weekly points (each day, the best
   players with a game start) become expected wins a week against every other team.

A candidate's score is your average expected wins over the 200 drafts. Every candidate
is played out on the same random draws, so the gaps between them are precise.

**Values (points):** FP/G is ESPN's projection under your league's scoring. Games are
ESPN's projection, adjusted for injury risk, and spread over the season by his NBA
team's schedule. Value is season points above replacement: (FP/G − replacement) ×
games, where replacement is the median FP/G of the 10 players just past the draft's
last pick.

**How the opponent model was checked.** Replaying two real drafts (DON FOOLIO and
Brooklyn), it predicted who'd still be there 10 picks later:

| Predicted to last | Players | Predicted | Actually lasted |
| --- | --- | --- | --- |
| Under 10% | 78 | 3% | 13% |
| 10-30% | 100 | 20% | 32% |
| 30-50% | 161 | 41% | 35% |
| 50-70% | 284 | 61% | 61% |
| 70-90% | 695 | 82% | 84% |
| 90% and over | 922 | 95% | 94% |

`python scripts/calibrate_draft.py --project league-lab-emk` refits it on every draft
ESPN has published for a registered league: the daily data pull still saves those
drafts for this, though the Draft page itself never uses a league.

## Limits

- **Projections drive everything.** Suggestions and "projected rank" use ESPN's
  projections. In the simulations you keep drafting by them while the others draft by
  ESPN's board, which favors you, and real seasons stray from projections.
- **Rarely-drafted players.** Players ESPN rates likely to go early sometimes last
  longer than predicted (the first row above), so a "he won't last" is a little
  pessimistic.
- **Pool.** The 400 best players by ESPN's points draft rank. A pick outside it holds a
  roster spot with no value.
- **Not yet supported:** keepers, auction drafts, adjusting a player's projection by
  hand, and categories drafts.
