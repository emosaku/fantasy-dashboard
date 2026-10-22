"""Making our projections and handing them to the ingest job.

* make_preseason: the model (model.py) on every loaded season, for one target season,
  written to the `projections` table (kind "preseason"). Re-running replaces that
  season's preseason rows for this MODEL_VERSION.
* latest: the newest projection run for a season, as per-game lines keyed by ESPN
  player id -- what the ingest job writes into each league's "projected" window.
"""

import pandas as pd
from google.cloud import bigquery

from ingest.bigquery_load import replace_rows
from ingest.projections.games import COLUMNS, STATS, from_columns, season_lines, to_columns
from ingest.projections.model import DEFAULT, fit_aging, project

MODEL_VERSION = "2026.10.1"  # bump when the model or its defaults change
PRESEASON = "preseason"


def load_history(client: bigquery.Client, project: str, dataset: str):
    """(season_lines for every loaded season, players with birth dates)."""
    stats = ", ".join(COLUMNS[s] for s in STATS)
    games = client.query(
        f"SELECT player_id, season, game_date, {stats} FROM `{project}.{dataset}.nba_player_games`"
    ).to_dataframe()
    players = client.query(
        f"SELECT player_id, birth_date FROM `{project}.{dataset}.nba_players`"
    ).to_dataframe()
    return season_lines(from_columns(games)), players


def preseason_rows(seasons, players, season: int, made_at) -> pd.DataFrame:
    """The model's preseason projections for `season`, in the projections table's shape.
    Only earlier seasons are used, even if some of this season is loaded."""
    known = seasons.loc[seasons["season"] < season]
    lines = project(known, season, players, DEFAULT, fit_aging(known, players, DEFAULT))
    rows = to_columns(lines)
    rows["made_at"] = made_at
    rows["model_version"] = MODEL_VERSION
    rows["kind"] = PRESEASON
    return rows


def make_preseason(client, project: str, dataset: str, season: int, made_at) -> int:
    seasons, players = load_history(client, project, dataset)
    rows = preseason_rows(seasons, players, season, made_at)
    scope = f"season = {int(season)} AND kind = '{PRESEASON}' AND model_version = '{MODEL_VERSION}'"
    return replace_rows(client, project, dataset, "projections", rows, scope)


def latest(client, project: str, dataset: str, season: int) -> pd.DataFrame:
    """The newest run's per-game lines for `season`, indexed by ESPN player id, in
    League Lab's stat names (GP = projected games). Empty if there's none yet."""
    columns = ", ".join(f"p.{COLUMNS[s]}" for s in [*STATS, "GP"])
    sql = (
        f"SELECT n.espn_player_id, {columns} FROM `{project}.{dataset}.projections` p "
        f"JOIN `{project}.{dataset}.nba_players` n USING (player_id) "
        f"WHERE p.season = {int(season)} AND n.espn_player_id IS NOT NULL "
        "QUALIFY p.made_at = MAX(p.made_at) OVER ()"
    )
    lines = from_columns(client.query(sql).to_dataframe())
    if lines.empty:
        return pd.DataFrame(columns=[*STATS, "GP"])
    lines["espn_player_id"] = lines["espn_player_id"].astype("int64")
    return lines.drop_duplicates("espn_player_id").set_index("espn_player_id")
