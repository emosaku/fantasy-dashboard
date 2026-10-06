"""The Trade & Waiver Analyzer's math: category weights and tiers, the all-play
objective E, and the waiver and trade searches. Pure pandas/numpy -- no Streamlit,
no BigQuery -- so every piece is unit-tested (tests/app/test_analysis.py).

Everything works on two frames:
  players -- one row per player_id: player_name, team_id (NaN for a free agent),
             is_free_agent, is_ir, injury_status, plus one z column per category
             (the league's own), from v_player_z for one stat window.
  totals  -- one row per team_id, one column per category: the sum of that team's
             non-IR players' z-scores (pool.team_totals).
"""
