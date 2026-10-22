import datetime as dt

from ingest.projections.run import MODEL_VERSION, PRESEASON, preseason_rows

from tests.projections.synthetic import league

AT = dt.datetime(2026, 10, 21, tzinfo=dt.UTC)


def test_preseason_rows_use_only_earlier_seasons_and_the_tables_columns():
    seasons, people = league(players=200, seasons=range(2020, 2027))
    rows = preseason_rows(seasons, people, 2026, AT)
    with_2026 = preseason_rows(seasons, people, 2026, AT)
    without = preseason_rows(seasons.loc[seasons["season"] < 2026], people, 2026, AT)
    assert with_2026.equals(without)  # 2026's own games never leak into its preseason
    assert {"player_id", "season", "gp", "fg3m", "tov", "min", "age"} <= set(rows)
    assert not any(c[0].isdigit() for c in rows)
    assert (rows["season"] == 2026).all() and (rows["kind"] == PRESEASON).all()
    assert (rows["model_version"] == MODEL_VERSION).all() and (rows["made_at"] == AT).all()
