import numpy as np
import pandas as pd
import pytest
from ingest.projections.model import (
    Params,
    fantasy_points,
    fit_aging,
    fit_regression,
    league_rates,
    project,
)

from tests.projections.synthetic import league, season_row

TARGET = 2027


def background(n=50):
    """Average players so the league rate is known: 0.5 PTS and 0.2 REB a minute."""
    return [
        season_row(1000 + i, s, 70, 2100, PTS=1050, REB=420, FGM=400, FGA=850)
        for i in range(n) for s in (2024, 2025, 2026)
    ]  # fmt: skip


FIXED = Params(regression_minutes=1000.0)  # the background has no real spread to fit


def run(rows, params=FIXED):
    seasons = pd.DataFrame(rows)
    return project(seasons, TARGET, params=params).set_index("player_id")


def test_long_history_keeps_his_own_rate():
    # 1.0 PTS a minute for three full seasons
    star = [season_row(1, s, 75, 2700, PTS=2700) for s in (2024, 2025, 2026)]
    out = run(star + background())
    rate = out.at[1, "PTS"] / out.at[1, "MIN"]
    assert 0.9 < rate < 1.0  # pulled a little toward the league's 0.5


def test_short_history_lands_near_league_average():
    cameo = [season_row(1, 2026, 5, 50, PTS=50)]  # 1.0 a minute, but only 50 minutes
    rows = cameo + background()
    out = run(rows)
    rate = out.at[1, "PTS"] / out.at[1, "MIN"]
    average = league_rates(pd.DataFrame(rows), 2026)["PTS"]  # ~0.5, him included
    assert rate == pytest.approx((50 + average * 1000) / (50 + 1000))


def test_recent_seasons_count_more():
    rising = [
        season_row(1, 2024, 70, 2100, PTS=630),  # 0.3 a minute
        season_row(1, 2025, 70, 2100, PTS=840),  # 0.4
        season_row(1, 2026, 70, 2100, PTS=1260),  # 0.6
    ]
    out = run(rising + background(), Params(regression_minutes=0.0))
    rate = out.at[1, "PTS"] / out.at[1, "MIN"]
    assert rate == pytest.approx((5 * 0.6 + 4 * 0.4 + 3 * 0.3) / 12)


def test_seasons_outside_the_window_are_ignored():
    rows = [season_row(1, 2020, 70, 2100, PTS=4200), season_row(1, 2026, 70, 2100, PTS=1050)]
    out = run(rows + background(), Params(regression_minutes=0.0))
    assert out.at[1, "PTS"] / out.at[1, "MIN"] == pytest.approx(0.5)


def test_shooting_percentages_follow_from_makes_and_attempts():
    shooter = [season_row(1, s, 75, 2500, FGM=500, FGA=1000) for s in (2024, 2025, 2026)]
    out = run(shooter + background())
    assert 0.47 < out.at[1, "FGM"] / out.at[1, "FGA"] < 0.5  # 50%, nudged toward 47%


def test_games_regress_toward_a_typical_season_and_never_pass_82():
    healthy = [season_row(1, s, 82, 2800) for s in (2024, 2025, 2026)]
    hurt = [season_row(2, 2026, 20, 600)]
    params = Params(regression_minutes=1000.0, games_prior=60.0, games_prior_weight=0.6)
    out = run(healthy + hurt + background(), params)
    assert out.at[1, "GP"] == pytest.approx((82 * 2.4 + 60 * 0.6) / 3.0)  # weights 1/.8/.6
    assert out.at[2, "GP"] == pytest.approx((20 * 1.0 + 60 * 0.6) / 1.6)
    assert (out["GP"] <= 82).all()


def test_minutes_regress_toward_a_rotation_player():
    params = Params(regression_minutes=1000.0, mpg_prior=18.0, mpg_prior_games=20.0)
    out = run([season_row(1, 2026, 4, 160)] + background(), params)
    assert out.at[1, "MIN"] == pytest.approx((160 + 18 * 20) / (4 + 20))


def test_players_without_history_are_not_projected():
    out = run(background())
    assert 1 not in out.index
    assert (out["season"] == TARGET).all()


def test_league_rates_are_minute_weighted():
    seasons = pd.DataFrame(background())
    assert league_rates(seasons, 2026)["PTS"] == pytest.approx(0.5)


def test_noisy_stats_regress_more_than_stable_ones():
    seasons, _ = league(players=500, seasons=range(2023, 2027))
    minutes = fit_regression(seasons, TARGET)
    assert minutes["STL"] > minutes["FGA"]
    assert minutes["BLK"] > minutes["3PA"]
    assert (minutes >= 50).all() and (minutes <= 20000).all()


def test_no_birth_dates_means_no_aging():
    seasons, _ = league(players=50, seasons=range(2023, 2027))
    assert fit_aging(seasons, None) is None
    out = project(seasons, TARGET)
    assert out["age"].isna().all()


def test_aging_fit_recovers_the_true_curve():
    seasons, people = league(players=600, seasons=range(2016, 2027))
    curve = fit_aging(seasons, people)
    young = curve.loc[22:25, "FGA"].mean()
    prime = curve.loc[28:30, "FGA"].mean()
    old = curve.loc[32:35, "FGA"].mean()
    assert young > 0.02 and old < -0.03 and abs(prime) < 0.02


def test_aging_moves_young_players_up_and_old_players_down():
    seasons, people = league(players=600, seasons=range(2016, 2027))
    curve = fit_aging(seasons, people)
    aged = project(seasons, TARGET, people, aging=curve).set_index("player_id")
    flat = project(seasons, TARGET, people).set_index("player_id")
    change = np.log(aged["FGA"] / flat["FGA"])
    assert change[aged["age"] < 25].mean() > 0
    assert change[aged["age"] > 32].mean() < 0


def test_fantasy_points_skip_stats_not_in_the_line():
    line = pd.DataFrame({"PTS": [20.0], "REB": [5.0]})
    assert fantasy_points(line, {"PTS": 1.0, "REB": 2.0, "DD": 5.0}).iloc[0] == 30.0
