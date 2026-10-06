"""Player rankings (app/analysis/rankings.py)."""

import pandas as pd

from analysis.rankings import player_rankings
from categories import NINE_CAT_NO_TO, keys

COLUMNS = keys(NINE_CAT_NO_TO)


def z_rows(player_id, name, team, zs, values=None):
    """v_player_z-shaped rows for one player: zs maps category -> z (others 0)."""
    return [
        {
            "player_id": player_id,
            "player_name": name,
            "team_id": team,
            "is_free_agent": team is None,
            "is_ir": False,
            "injury_status": "ACTIVE",
            "position": "G",
            "category": c,
            "display_order": i,
            "z": zs.get(c, 0.0),
            "value": (values or {}).get(c, 1.0),
        }
        for i, c in enumerate(COLUMNS)
    ]


def league():
    return pd.DataFrame(
        z_rows(1, "Star", 10, {"PTS": 2.0, "BLK": 1.0})
        + z_rows(2, "Shot blocker", 4, {"BLK": 3.0, "PTS": -1.0})
        + z_rows(3, "Free agent", None, {"PTS": 2.0, "AST": -2.0})
    )


def test_category_ranks_are_league_wide_with_shared_ties():
    ranks = player_rankings(league()).set_index("player_name")
    assert ranks.loc["Shot blocker", "BLK_rank"] == 1
    assert ranks.loc["Star", "BLK_rank"] == 2
    # Star and the free agent tie on points: both rank 1, the next player is 3rd.
    assert ranks.loc["Star", "PTS_rank"] == ranks.loc["Free agent", "PTS_rank"] == 1
    assert ranks.loc["Shot blocker", "PTS_rank"] == 3


def test_overall_is_the_sum_of_z_and_drives_the_order():
    ranks = player_rankings(league())
    assert list(ranks["player_name"]) == ["Star", "Shot blocker", "Free agent"]
    assert list(ranks["overall_rank"]) == [1, 2, 3]
    assert ranks.iloc[0]["total_z"] == 3.0


def test_keeps_values_and_free_agent_flag():
    ranks = player_rankings(league()).set_index("player_name")
    assert ranks.loc["Free agent", "is_free_agent"]
    assert ranks.loc["Star", "PTS_value"] == 1.0
    assert {f"{c}_{kind}" for c in COLUMNS for kind in ("value", "z", "rank")} <= set(ranks.columns)
