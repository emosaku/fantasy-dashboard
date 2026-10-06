"""Precomputed per-league tables: the dashboard reads these small m_* tables, never
the views. Each is a copy of one view, clustered by league_id, so a dashboard query
for one league scans only that league's rows.

Ingest refreshes the rows for the leagues it just loaded -- one DELETE + INSERT per
table per task, covering all of that task's leagues at once, so the cost doesn't
grow with every league. scripts/apply_sql.py rebuilds them whole when views change.
"""

# In dependency-free order; each m_<view> mirrors sql/views/*_<view>.sql.
MATERIALIZED_VIEWS = [
    "v_team_week_cats",
    "v_all_play",
    "v_power_rankings",
    "v_luck",
    "v_transactions",
    "v_player_pool",
    "v_player_z",
    "v_category_ranks",
    "v_player_profile",
    "v_roster_strength",
]


def table_for(view: str) -> str:
    return "m_" + view.removeprefix("v_")


def refresh_statements(project: str, dataset: str, league_ids: list[int]) -> list[str]:
    """DELETE + INSERT per materialized table for these leagues."""
    ids = ", ".join(str(int(i)) for i in sorted(set(league_ids)))
    out = []
    for view in MATERIALIZED_VIEWS:
        table = f"`{project}.{dataset}.{table_for(view)}`"
        source = f"`{project}.{dataset}.{view}`"
        out.append(f"DELETE FROM {table} WHERE league_id IN ({ids})")
        out.append(f"INSERT INTO {table} SELECT * FROM {source} WHERE league_id IN ({ids})")
    return out


def rebuild_statement(project: str, dataset: str, view: str) -> str:
    """Re-create one materialized table from its view (schema changes, first deploy)."""
    return (
        f"CREATE OR REPLACE TABLE `{project}.{dataset}.{table_for(view)}` "
        f"CLUSTER BY league_id AS SELECT * FROM `{project}.{dataset}.{view}`"
    )
