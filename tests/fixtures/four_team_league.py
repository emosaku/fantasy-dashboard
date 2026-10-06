"""A synthetic 4-team league for the analysis tests: 4 players per team plus 3 free
agents, with z-scores built so a few facts are known in advance.

  * Team 1 runs away with BLK: each player +1.5 BLK, a lead far beyond delta = 1.0.
  * Team 4 is hopeless in AST: each player -1.5 AST, trailing everyone by > 1.0.
  * Player 41 (team 4) is on IR.
  * Free agent 103 is great at STL and solid elsewhere; 102 is OUT.
Everything else is small seeded noise, so totals are realistic but reproducible.
"""

import numpy as np
import pandas as pd

from categories import NINE_CAT_NO_TO, keys

COLUMNS = keys(NINE_CAT_NO_TO)


def build_players() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    rows = []
    for team in (1, 2, 3, 4):
        for k in range(4):
            pid = team * 10 + k
            z = dict(zip(COLUMNS, rng.normal(0, 0.4, len(COLUMNS)), strict=True))
            if team == 1:
                z["BLK"] += 1.5
            if team == 4:
                z["AST"] -= 1.5
            rows.append(
                {
                    "player_id": pid,
                    "player_name": f"P{pid}",
                    "team_id": team,
                    "is_free_agent": False,
                    "is_ir": pid == 41,
                    "injury_status": "ACTIVE",
                    "position": "G",
                    **z,
                }
            )
    for pid, status in ((101, "ACTIVE"), (102, "OUT"), (103, "ACTIVE")):
        z = dict(zip(COLUMNS, rng.normal(0, 0.3, len(COLUMNS)), strict=True))
        if pid == 103:
            z = {c: 0.4 for c in COLUMNS} | {"STL": 2.5}
        if pid == 102:
            z = {c: 3.0 for c in COLUMNS}  # best player in the pool -- but OUT
        rows.append(
            {
                "player_id": pid,
                "player_name": f"FA{pid}",
                "team_id": np.nan,
                "is_free_agent": True,
                "is_ir": False,
                "injury_status": status,
                "position": "F",
                **z,
            }
        )
    return pd.DataFrame(rows).set_index("player_id")
