import pandas as pd
from ingest.projections.bonus import add_bonus, bonus_rates
from ingest.projections.games import STATS


def games_of(pid, season, count, dd_every=None, pf=2.0):
    rows = []
    for i in range(count):
        dd = dd_every is not None and i % dd_every == 0
        row = {s: 0.0 for s in STATS} | {"MIN": 30.0, "PTS": 20.0, "REB": 12.0 if dd else 5.0}
        rows.append({"player_id": pid, "season": season, "PF": pf} | row)
    return rows


def test_a_regular_double_double_keeps_his_rate():
    games = pd.DataFrame(games_of(1, 2026, 70, dd_every=1) + games_of(2, 2026, 70))
    rates, league = bonus_rates(games, 2027)
    assert league["DD"] == 0.5
    assert 0.9 < rates.at[1, "DD"] < 1.0  # pulled only a little toward the league's 0.5
    assert 0.0 < rates.at[2, "DD"] < 0.1
    assert rates.at[1, "PF"] == 2.0


def test_few_games_stay_near_the_league_rate():
    games = pd.DataFrame(games_of(1, 2026, 70, dd_every=2) + games_of(9, 2027, 2, dd_every=1))
    rates, league = bonus_rates(games, 2027)
    assert rates.at[9, "DD"] < 0.75  # two double-doubles in two games isn't a 100% rate


def test_older_seasons_count_less_and_anyone_unseen_gets_the_league_rate():
    games = pd.DataFrame(games_of(1, 2024, 70, dd_every=1) + games_of(2, 2026, 70))
    rates, league = bonus_rates(games, 2027)
    assert 1 not in rates.index  # three seasons back: out of the window
    lines = pd.DataFrame({"player_id": [2, 5], "PTS": [10.0, 8.0]})
    out = add_bonus(lines, rates, league).set_index("player_id")
    assert out.at[5, "DD"] == league["DD"]
