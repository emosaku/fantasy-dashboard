import pandas as pd
import pytest
from ingest.projections.backtest import backtest, last_season, per_game, tune
from ingest.projections.model import Params

from tests.projections.synthetic import league, season_row

TESTS = [2024, 2025, 2026]


@pytest.fixture(scope="module")
def synthetic():
    return league(players=500, seasons=range(2017, 2027))


def test_model_beats_repeating_last_season(synthetic):
    seasons, people = synthetic
    scored = backtest(seasons, TESTS, people).set_index(["season", "method"])
    for season in TESTS:
        model, base = scored.loc[(season, "model")], scored.loc[(season, "last_season")]
        assert model["mae_fpg"] < base["mae_fpg"]
        assert model["mae_fp"] < base["mae_fp"]
        assert model["players"] == base["players"] > 100


def test_other_projections_are_scored_on_the_same_players(synthetic):
    seasons, people = synthetic
    # a "perfect" outside projection for 2026 covering only half the players
    actual = per_game(seasons.loc[seasons["season"] == 2026])
    half = actual.loc[actual["player_id"] % 2 == 0]
    scored = backtest(seasons, [2026], people, others={"oracle": {2026: half}})
    by = scored.set_index("method")
    assert by.at["oracle", "mae_fpg"] == pytest.approx(0.0)
    assert by["players"].nunique() == 1
    assert by.at["model", "players"] <= len(half)


def test_last_season_is_the_previous_line_per_game():
    seasons = pd.DataFrame([season_row(1, 2026, 50, 1500, PTS=1000)])
    base = last_season(seasons, 2027).set_index("player_id")
    assert (base.at[1, "PTS"], base.at[1, "MIN"], base.at[1, "GP"]) == (20.0, 30.0, 50)


def test_tune_picks_the_best_combination(synthetic):
    seasons, people = synthetic
    best, table = tune(seasons, [2026], people, grid={"regression_minutes": [0.0, 1000.0]})
    assert isinstance(best, Params)
    assert len(table) == 2
    assert best.regression_minutes == table.iloc[0]["regression_minutes"]
    assert table["mae_fpg"].is_monotonic_increasing
