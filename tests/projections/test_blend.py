import pandas as pd
import pytest
from ingest.projections.blend import blend
from ingest.projections.games import STATS


def line(pid, gp, mpg, pts_per_min):
    row = {s: 0.0 for s in STATS} | {"MIN": mpg, "PTS": pts_per_min * mpg}
    return {"player_id": pid, "GP": gp} | row


def totals(pid, gp, minutes, pts):
    row = {s: 0.0 for s in STATS} | {"MIN": minutes, "PTS": pts}
    return {"player_id": pid, "season": 2027, "GP": gp} | row


PRE = pd.DataFrame([line(1, 82, 30.0, 0.5)])


def test_no_games_yet_keeps_the_preseason_line():
    out = blend(PRE, pd.DataFrame([totals(9, 1, 10, 5)]), 82).set_index("player_id")
    assert out.at[1, "PTS"] == pytest.approx(15.0)
    assert out.at[1, "GP"] == pytest.approx(82)


def test_a_long_season_outweighs_the_preseason_line():
    now = pd.DataFrame([totals(1, 60, 2400, 2400)])  # 40 mpg, 1.0 a minute
    out = blend(PRE, now, 22).set_index("player_id")
    assert out.at[1, "PTS"] / out.at[1, "MIN"] == pytest.approx((300 + 2400) / (600 + 2400))
    assert out.at[1, "MIN"] == pytest.approx((30 * 15 + 2400) / (15 + 60))


def test_a_rookie_without_a_projection_uses_his_own_line():
    out = blend(PRE, pd.DataFrame([totals(2, 10, 250, 150)]), 70).set_index("player_id")
    assert out.at[2, "MIN"] == pytest.approx(25.0)
    assert out.at[2, "PTS"] == pytest.approx(15.0)
    assert out.at[2, "GP"] == pytest.approx(70)


def test_games_left_scale_by_how_often_he_plays():
    pre = pd.DataFrame([line(1, 41, 30.0, 0.5)])  # plays half the time
    left = pd.Series({1: 40})
    out = blend(pre, pd.DataFrame([totals(1, 5, 150, 75)]), left).set_index("player_id")
    assert out.at[1, "GP"] == pytest.approx(20)
