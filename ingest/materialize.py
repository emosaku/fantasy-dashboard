"""Precomputed per-league tables: the dashboard reads these small m_* tables, never
the views. Each is a copy of one view, clustered by league_id, so a dashboard query
for one league scans only that league's rows.

Ingest refreshes the rows for the leagues it just loaded -- one DELETE + INSERT per
table per task, covering all of that task's leagues at once, so the cost doesn't
grow with every league. scripts/apply_sql.py rebuilds them whole when views change.

Then the daily snapshots (sql/ddl/19_league_snapshots.sql): a dated copy of what the
current-state tables overwrite, the league history only League Lab has. Same pattern:
the day's rows for these leagues are replaced, so re-running a day never doubles it.
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


# snap_<name>: (source table, its columns copied, extra filter). Explicit columns, so a
# column added to a source table never breaks or reshapes the history.
SNAPSHOTS = {
    "snap_rosters": ("rosters", ["league_id", "season", "team_id", "player_id", "player_name",
                                 "lineup_slot", "injury_status", "pro_team"], ""),
    "snap_standings": ("teams", ["league_id", "season", "team_id", "team_name", "owner", "wins",
                                 "losses", "ties", "points_for", "points_against", "standing"],
                       ""),
    "snap_category_ranks": ("m_category_ranks", ["league_id", "season", "stat_window", "lens",
                                                 "team_id", "category", "value", "win_rate",
                                                 "rank", "gap_above", "gap_below"], ""),
    "snap_player_z": ("m_player_z", ["league_id", "season", "stat_window", "player_id",
                                     "team_id", "category", "value", "z"],
                      "stat_window IN ('season', 'projected')"),
    "snap_player_points": ("player_points", ["league_id", "season", "stat_window", "player_id",
                                             "fp_per_game", "games"],
                           "stat_window IN ('season', 'projected')"),
}  # fmt: skip


def snapshot_statements(project: str, dataset: str, league_ids: list[int], day) -> list[str]:
    """Replace `day`'s snapshot rows for these leagues with the current state. Run
    after refresh_statements, which the m_* sources depend on."""
    ids = ", ".join(str(int(i)) for i in sorted(set(league_ids)))
    out = []
    for snap, (source, columns, extra) in SNAPSHOTS.items():
        table = f"`{project}.{dataset}.{snap}`"
        where = f"league_id IN ({ids})" + (f" AND {extra}" if extra else "")
        cols = ", ".join(columns)
        out.append(f"DELETE FROM {table} WHERE snapshot_date = DATE '{day}' "
                   f"AND league_id IN ({ids})")  # fmt: skip
        out.append(f"INSERT INTO {table} (snapshot_date, {cols}) SELECT DATE '{day}', {cols} "
                   f"FROM `{project}.{dataset}.{source}` WHERE {where}")  # fmt: skip
    return out
