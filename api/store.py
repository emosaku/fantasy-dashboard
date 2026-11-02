"""Everything the API reads or writes outside itself, behind one object, so the
endpoints never touch BigQuery or Firestore directly and the tests can swap in fixture
data (tests/api/conftest.py).

* Leagues and memberships: the Firestore registry, through app/tenancy.py (the same
  functions the Streamlit pages use).
* League tables: BigQuery, through app/reads.py, cached in memory per league and data
  version (the league's last_ingested_at): new data shows up as soon as it lands and
  nothing is cleared by hand. Always one league per read.
* The trade finder cache and the history views (sql/ddl/21, sql/views/12-14).
"""

import datetime as dt
import json
import os
import threading
from collections import OrderedDict

import pandas as pd

import reads
import saved_store
import tenancy

TABLE_CACHE = 256  # league tables kept in memory (each is one league's rows)
HISTORY = {  # metric -> view
    "category_ranks": "v_rank_history",
    "standings": "v_standing_history",
    "player_values": "v_player_value_history",
}


class LRU:
    def __init__(self, size: int):
        self.size, self.items, self.lock = size, OrderedDict(), threading.Lock()

    def get(self, key):
        with self.lock:
            if key in self.items:
                self.items.move_to_end(key)
                return self.items[key]
        return None

    def put(self, key, value):
        with self.lock:
            self.items[key] = value
            self.items.move_to_end(key)
            while len(self.items) > self.size:
                self.items.popitem(last=False)
        return value


class BigQueryTables:
    """League tables, history views and the finder cache in BigQuery."""

    def __init__(self, project: str, dataset: str, location: str = "us-west1"):
        from google.cloud import bigquery

        self.bigquery = bigquery
        self.project, self.dataset = project, dataset
        self.client = bigquery.Client(project=project, location=location)

    def read(self, table: str, league_id: int) -> pd.DataFrame:
        return reads.league_rows(self.client, self.project, self.dataset, table, league_id)

    def _params(self, **values):
        types = {int: "INT64", str: "STRING", dt.date: "DATE"}
        return self.bigquery.QueryJobConfig(query_parameters=[
            self.bigquery.ScalarQueryParameter(k, types[type(v)], v) for k, v in values.items()
        ])  # fmt: skip

    def history(self, view: str, league_id: int, start: dt.date, end: dt.date) -> pd.DataFrame:
        sql = (f"SELECT * FROM `{self.project}.{self.dataset}.{view}` WHERE league_id = "
               "@league_id AND snapshot_date BETWEEN @start AND @end")  # fmt: skip
        job = self.client.query(sql, job_config=self._params(league_id=int(league_id),
                                                             start=start, end=end))  # fmt: skip
        return job.to_dataframe(create_bqstorage_client=False)

    def finder_get(self, league_id, team_id, window, version) -> list | None:
        sql = (f"SELECT deals FROM `{self.project}.{self.dataset}.trade_finder_cache` "
               "WHERE league_id = @league_id AND team_id = @team_id AND stat_window = @window "
               "AND data_version = @version")  # fmt: skip
        job = self.client.query(
            sql,
            job_config=self._params(
                league_id=int(league_id), team_id=int(team_id), window=window, version=version
            ),
        )
        rows = list(job.result())
        return json.loads(rows[0].deals) if rows else None

    def finder_put(self, league_id, team_id, window, version, deals: list, now) -> None:
        from ingest.bigquery_load import replace_rows

        frame = pd.DataFrame([{
            "league_id": int(league_id), "team_id": int(team_id), "stat_window": window,
            "data_version": version, "computed_at": now, "deals": json.dumps(deals),
        }])  # fmt: skip
        scope = (f"league_id = {int(league_id)} AND team_id = {int(team_id)} "
                 f"AND stat_window = '{window}'")  # fmt: skip
        replace_rows(self.client, self.project, self.dataset, "trade_finder_cache", frame, scope)


class Store:
    def __init__(self, db, tables, settings: dict, run_job=None, preview=None):
        """db: Firestore client; tables: BigQueryTables or a test double; settings:
        season, max_leagues, max_per_user; run_job(league_id): start its refresh;
        preview(league_id, season): onboarding.preview."""
        self.db, self.tables, self.settings = db, tables, settings
        self._run_job, self._preview = run_job, preview
        self.cache = LRU(TABLE_CACHE)

    # --- Registry ---
    def league(self, league_id: int) -> dict | None:
        doc = tenancy.get_league(self.db, int(league_id))
        return None if doc is None else {"league_id": int(league_id), **doc}

    def memberships(self, uid: str) -> list[dict]:
        return tenancy.memberships(self.db, uid)

    def upsert_user(self, user: dict, now) -> None:
        tenancy.upsert_user(self.db, user, now)

    # --- League tables ---
    def table(self, league_id: int, version: str, name: str) -> pd.DataFrame:
        key = (name, int(league_id), version)
        found = self.cache.get(key)
        if found is None:
            found = self.cache.put(key, self.tables.read(name, int(league_id)))
        return found

    def history(self, league_id: int, version: str, metric: str, start: dt.date,
                end: dt.date) -> pd.DataFrame:  # fmt: skip
        """Snapshot history; cached per data version, since snapshots only change with a
        data load."""
        key = ("history", int(league_id), version, metric, start, end)
        found = self.cache.get(key)
        if found is None:
            found = self.cache.put(key, self.tables.history(HISTORY[metric], int(league_id),
                                                            start, end))  # fmt: skip
        return found

    # --- Trade finder cache ---
    def finder_get(self, league_id, team_id, window, version):
        key = ("finder", int(league_id), int(team_id), window, version)
        found = self.cache.get(key)
        if found is None:
            found = self.tables.finder_get(league_id, team_id, window, version)
            if found is not None:
                self.cache.put(key, found)
        return found

    def finder_put(self, league_id, team_id, window, version, deals, now) -> None:
        self.tables.finder_put(league_id, team_id, window, version, deals, now)
        self.cache.put(("finder", int(league_id), int(team_id), window, version), deals)

    # --- Saved trades (app/saved_store.py) ---
    def saved_load(self, league_id, uid, team_id):
        return saved_store.load(self.db, league_id, uid, team_id)

    def saved_save(self, league_id, uid, trade) -> None:
        saved_store.save(self.db, league_id, uid, trade)

    def saved_delete(self, league_id, uid, trade_id) -> None:
        saved_store.delete(self.db, league_id, uid, trade_id)

    # --- Refresh and onboarding ---
    def refresh(self, league: dict, now) -> None:
        tenancy.claim_refresh(self.db, league, now)
        self._run_job(league["league_id"])

    def preview(self, league_id: int) -> dict:
        return self._preview(int(league_id), self.settings["season"])

    def register(self, league_id: int, user: dict, team_id, preview: dict, now) -> dict:
        doc = tenancy.register(
            self.db, league_id, self.settings["season"], user, team_id,
            preview["league_name"], now, self.settings["max_leagues"],
            self.settings["max_per_user"], league_format=preview["format"],
        )  # fmt: skip
        self._run_job(int(league_id))
        return doc


def from_env(env=os.environ) -> Store:
    """The production store: Firestore and BigQuery in GCP_PROJECT_ID."""
    from google.cloud import firestore

    import onboarding
    import refresh

    project = env["GCP_PROJECT_ID"]
    return Store(
        firestore.Client(project=project),
        BigQueryTables(
            project,
            env.get("BIGQUERY_DATASET", "league_lab"),
            env.get("BIGQUERY_LOCATION", "us-west1"),
        ),  # fmt: skip
        {
            "season": int(env.get("SEASON", "2027")),
            "max_leagues": int(env.get("MAX_LEAGUES", "10")),
            "max_per_user": int(env.get("MAX_LEAGUES_PER_USER", "3")),
        },  # fmt: skip
        run_job=refresh.ingest_league,
        preview=onboarding.preview,
    )
