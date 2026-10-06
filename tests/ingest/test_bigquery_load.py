"""The SQL the loader and the materialized-table refresh send -- built as strings,
so they're testable without BigQuery."""

import numpy as np
from ingest.bigquery_load import in_list, league_scope, replace_sql
from ingest.materialize import MATERIALIZED_VIEWS, refresh_statements, table_for


def test_replace_deletes_only_inside_the_scope_then_inserts():
    sql = replace_sql(
        "p.d.rosters", "p.d.rosters__stage", ["league_id", "team_id"], "league_id = 7"
    )
    assert sql.splitlines() == [
        "DELETE FROM `p.d.rosters` WHERE league_id = 7;",
        "INSERT INTO `p.d.rosters` (league_id, team_id) SELECT league_id, team_id "
        "FROM `p.d.rosters__stage`;",
    ]


def test_league_scope_always_starts_with_the_league():
    assert league_scope(7) == "league_id = 7"
    assert league_scope(7, "season = 2026") == "league_id = 7 AND season = 2026"


def test_in_list_renders_ints_including_numpy_and_quotes_strings():
    assert in_list("matchup_period", [1, np.int64(2)]) == "matchup_period IN (1, 2)"
    assert in_list("txn_id", ["ab", "c'd"]) == "txn_id IN ('ab', 'cd')"  # quote stripped


def test_materialized_refresh_touches_only_these_leagues():
    statements = refresh_statements("p", "d", [3, 1, 3])
    assert len(statements) == 2 * len(MATERIALIZED_VIEWS)
    assert statements[0] == "DELETE FROM `p.d.m_team_week_cats` WHERE league_id IN (1, 3)"
    assert statements[1] == (
        "INSERT INTO `p.d.m_team_week_cats` SELECT * FROM `p.d.v_team_week_cats` "
        "WHERE league_id IN (1, 3)"
    )
    assert table_for("v_player_z") == "m_player_z"
