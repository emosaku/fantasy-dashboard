"""Trade Analyzer page (Step 6, added after the original proposal): pick "your team"
and a trade partner from the league; pick players from each roster by clicking their
name, which moves them into a selected-to-trade section below (click again to
remove). Shows both sides' category totals/averages before the trade, after the
trade, and the delta. Reads v_team_roster_stats. The before/after/delta math runs
here in the app, not in SQL -- the one page where that's deliberate, since the
player selection is arbitrary and can't be precomputed. Not implemented yet.
"""
