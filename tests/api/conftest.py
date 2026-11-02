"""The API against two fixture leagues, with no Google services:

* League 1001, categories (9-cat, no TO): tests/fixtures/four_team_league.py's players
  as the m_player_z rows, plus small hand-made weekly results.
* League 2002, points: tests/fixtures/points_league.py's players, NBA schedule and
  lineup rules, two weeks played.

Firestore is the in-memory fake; BigQuery is FakeTables (frames by table name);
sign-in is a test issuer with its own RSA key, so tokens are real signed JWTs."""

import datetime as dt
import sys
from pathlib import Path

import jwt
import numpy as np
import pandas as pd
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

from api.main import create_app  # noqa: E402
from api.store import Store  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from api import auth, services  # noqa: E402
from categories import NINE_CAT_NO_TO, stats_needed  # noqa: E402
from tests.fixtures import four_team_league as cat_fx  # noqa: E402
from tests.fixtures import points_league as pts_fx  # noqa: E402
from tests.fixtures.fake_firestore import FakeFirestore  # noqa: E402

CATS, PTS = 1001, 2002
ISSUER, AUDIENCE = "https://issuer.test", "league-lab-web"
LOADED = dt.datetime(2026, 11, 2, 12, tzinfo=dt.UTC)
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
CAT_RECORDS = [
    {"category": c.key, "kind": c.kind, "num_stat": c.num, "den_stat": c.den,
     "lower_is_better": c.lower_is_better, "display_order": i}
    for i, c in enumerate(NINE_CAT_NO_TO)
]  # fmt: skip
SCORING = [{"stat": "PTS", "points": 1.0}, {"stat": "REB", "points": 1.2},
           {"stat": "AST", "points": 1.5}, {"stat": "DD", "points": 5.0},
           {"stat": "EJ", "points": -5.0}]  # fmt: skip


class Keys:
    def get_signing_key_from_jwt(self, token):
        class Found:
            key = KEY.public_key()

        return Found()


def token(sub="u1", email="ann@example.com", audience=AUDIENCE, issuer=ISSUER, minutes=30):
    now = dt.datetime.now(dt.UTC)
    claims = {"sub": sub, "email": email, "name": sub.upper(), "aud": audience, "iss": issuer,
              "iat": now, "exp": now + dt.timedelta(minutes=minutes)}  # fmt: skip
    return jwt.encode(claims, KEY, algorithm="RS256", headers={"kid": "test"})


def signed(sub="u1"):
    return {"Authorization": f"Bearer {token(sub)}"}


# --- League 1001: categories ----------------------------------------------------------


def cat_player_z() -> pd.DataFrame:
    players = cat_fx.build_players()
    rows = []
    for window in ("blended", "season"):
        for pid, p in players.iterrows():
            for order, col in enumerate(cat_fx.COLUMNS):
                rows.append({
                    "league_id": CATS, "season": 2027, "stat_window": window, "player_id": pid,
                    "player_name": p["player_name"], "position": p["position"], "pro_team": "X",
                    "team_id": p["team_id"], "is_free_agent": p["is_free_agent"],
                    "is_ir": p["is_ir"], "lineup_slot": "BE", "injury_status": p["injury_status"],
                    "category": col, "kind": "count", "lower_is_better": False,
                    "display_order": order, "num": p[col], "den": 0.0, "value": p[col],
                    "z": p[col],
                })  # fmt: skip
    return pd.DataFrame(rows)


def cat_pool(player_z: pd.DataFrame) -> pd.DataFrame:
    """Per-game stat lines (season and projected) for every player, for the
    projected finish: a seeded line per stat the categories need."""
    rng = np.random.default_rng(3)
    info = player_z.drop_duplicates("player_id")
    rows = []
    for _, p in info.iterrows():
        for window in ("season", "projected"):
            line = {s: float(rng.uniform(1, 20)) for s in stats_needed(NINE_CAT_NO_TO)}
            line["FGA"], line["FTA"] = line["FGM"] * 2.1, line["FTM"] * 1.3
            line["GP"] = 8.0
            for stat, value in line.items():
                rows.append({**{k: p[k] for k in ("league_id", "season", "player_id",
                                                  "player_name", "position", "pro_team",
                                                  "team_id", "lineup_slot", "injury_status",
                                                  "is_free_agent", "is_ir")},
                             "expected_return_date": None, "eligible_slots": "G,UT",
                             "stat_window": window, "stat": stat, "value": value})  # fmt: skip
    return pd.DataFrame(rows)


def cat_weeks() -> tuple[pd.DataFrame, pd.DataFrame]:
    """(m_team_week_cats, m_luck) for weeks 1-2: 1 v 2 and 3 v 4, then 1 v 3, 2 v 4."""
    rng = np.random.default_rng(5)
    cats, luck = [], []
    pairs = {1: [(1, 2), (3, 4)], 2: [(1, 3), (2, 4)]}
    for week, games in pairs.items():
        for a, b in games:
            for team, opp in ((a, b), (b, a)):
                for order, col in enumerate(cat_fx.COLUMNS):
                    value = float(rng.uniform(1, 10))
                    cats.append({"league_id": CATS, "season": 2027, "matchup_period": week,
                                 "team_id": team, "opponent_id": opp, "category": col,
                                 "kind": "count", "lower_is_better": False,
                                 "display_order": order, "num": value, "den": 0.0,
                                 "value": value, "score": value})  # fmt: skip
                luck.append({"league_id": CATS, "season": 2027, "matchup_period": week,
                             "team_id": team, "team_name": f"Team {team}", "opponent_id": opp,
                             "opponent_name": f"Team {opp}", "cat_wins": 5, "cat_losses": 4,
                             "cat_ties": 0, "actual_result": "W" if team == a else "L",
                             "ap_wins": 2, "ap_losses": 1, "ap_ties": 0, "ap_win_pct": 0.667,
                             "luck_week": 0.33 if team == a else -0.33,
                             "actual_win_pct_to_date": 0.5, "ap_win_pct_to_date": 0.5,
                             "luck": 0.0})  # fmt: skip
    return pd.DataFrame(cats), pd.DataFrame(luck)


def cat_tables() -> dict:
    z = cat_player_z()
    week_cats, luck = cat_weeks()
    teams = pd.DataFrame([{"league_id": CATS, "season": 2027, "team_id": t,
                           "team_name": f"Team {t}", "owner": f"Owner {t}", "wins": 2 - (t > 2),
                           "losses": t > 2, "ties": 0, "points_for": 0.0, "points_against": 0.0,
                           "standing": t} for t in (1, 2, 3, 4)])  # fmt: skip
    all_play = pd.DataFrame([{"league_id": CATS, "season": 2027, "matchup_period": w,
                              "team_id": t, "ap_wins": 2, "ap_losses": 1, "ap_ties": 0,
                              "ap_win_pct": 0.667, "ap_cat_wins": 15, "ap_cat_losses": 12,
                              "ap_cat_ties": 0, "ap_cat_win_pct": 0.55}
                             for w in (1, 2) for t in (1, 2, 3, 4)])  # fmt: skip
    power = pd.DataFrame(
        [
            {
                "league_id": CATS,
                "season": 2027,
                "matchup_period": w,
                "team_id": t,
                "team_name": f"Team {t}",
                "power_rank": t,
                "ap_wins": 2,
                "ap_losses": 1,
                "ap_ties": 0,
                "ap_win_pct": 0.667,
                "ap_cat_wins": 15,
                "ap_cat_losses": 12,
                "ap_cat_ties": 0,
                "ap_cat_win_pct": 0.55,
            }
            for w in (1, 2)
            for t in (1, 2, 3, 4)
        ]
    )
    txns = pd.DataFrame([
        {"league_id": CATS, "season": 2027, "txn_id": "a", "team_id": 1, "team_name": "Team 1",
         "txn_date": pd.Timestamp("2026-10-25 18:00", tz="UTC"), "action": "ADDED",
         "action_type": "add", "player_id": 101, "player_name": "FA101", "detail": None},
        {"league_id": CATS, "season": 2027, "txn_id": "b", "team_id": 2, "team_name": "Team 2",
         "txn_date": pd.Timestamp("2026-10-30 18:00", tz="UTC"), "action": "TRADED",
         "action_type": "trade", "player_id": 20, "player_name": "P20", "detail": None},
    ])  # fmt: skip
    strength = pd.DataFrame(
        [
            {
                "league_id": CATS,
                "season": 2027,
                "stat_window": "blended",
                "team_id": t,
                "team_name": f"Team {t}",
                "category": c,
                "display_order": i,
                "players": 4,
                "value": 1.0,
                "z": 0.0,
            }
            for t in (1, 2, 3, 4)
            for i, c in enumerate(cat_fx.COLUMNS)
        ]
    )
    ranks = pd.DataFrame([{"league_id": CATS, "season": 2027, "stat_window": "blended",
                           "lens": "roster", "team_id": t, "team_name": f"Team {t}",
                           "category": c, "value": 1.0, "win_rate": 0.5, "rank": t,
                           "gap_above": 0.1, "gap_below": 0.1}
                          for t in (1, 2, 3, 4) for c in cat_fx.COLUMNS])  # fmt: skip
    profile = pd.DataFrame([{"league_id": CATS, "season": 2027, "player_id": 10,
                             "injured": False, "injury_status": "ACTIVE",
                             "expected_return_date": None, "avg_games_played": 70.0,
                             "seasons_counted": 3, "gp_last_season": 72.0,
                             "gp_2_seasons_ago": 68.0, "gp_3_seasons_ago": 70.0}])  # fmt: skip
    return {"m_player_z": z, "m_player_pool": cat_pool(z), "m_team_week_cats": week_cats,
            "m_luck": luck, "teams": teams, "m_all_play": all_play, "m_power_rankings": power,
            "m_transactions": txns, "m_roster_strength": strength, "m_category_ranks": ranks,
            "m_player_profile": profile}  # fmt: skip


# --- League 2002: points --------------------------------------------------------------


def pts_tables() -> dict:
    players = pts_fx.build_players()
    pool, points = [], []
    for pid, p in players.iterrows():
        info = {"league_id": PTS, "season": 2027, "player_id": pid,
                "player_name": p["player_name"], "position": p["position"],
                "pro_team": p["pro_team"], "team_id": p["team_id"],
                "lineup_slot": p["lineup_slot"], "injury_status": p["injury_status"],
                "expected_return_date": None, "eligible_slots": p["eligible_slots"],
                "is_free_agent": p["is_free_agent"], "is_ir": p["is_ir"]}  # fmt: skip
        for window in ("season", "projected"):
            line = {"PTS": p["fpg"] * 0.6, "REB": p["fpg"] * 0.15, "AST": p["fpg"] * 0.1,
                    "DD": 0.2, "GP": 8.0}  # fmt: skip
            for stat, value in line.items():
                pool.append({**info, "stat_window": window, "stat": stat, "value": value})
            points.append({"league_id": PTS, "season": 2027, "player_id": pid,
                           "stat_window": window, "fp_per_game": p["fpg"],
                           "fp_total": p["fpg"] * 8, "games": 8.0,
                           "computed_per_game": p["fpg"], "source": "computed"})  # fmt: skip
    schedule = pts_fx.schedule().assign(league_id=PTS, season=2027)
    scores = []
    for week, games in {1: [(1, 2, 610.0, 590.0), (3, 4, 550.0, 575.0)],
                        2: [(1, 3, 600.0, 540.0), (2, 4, 580.0, 585.0)]}.items():  # fmt: skip
        for a, b, pa, pb in games:
            for team, opp, mine, theirs in ((a, b, pa, pb), (b, a, pb, pa)):
                scores.append(
                    {
                        "league_id": PTS,
                        "season": 2027,
                        "matchup_period": week,
                        "team_id": team,
                        "opponent_id": opp,
                        "points": mine,
                        "opponent_points": theirs,
                        "is_playoff": False,
                        "winner": "HOME" if pa > pb else "AWAY",
                        "is_home": team == a,
                    }
                )
    for week, a, b in ((3, 1, 4), (3, 2, 3)):
        for team, opp in ((a, b), (b, a)):
            scores.append({"league_id": PTS, "season": 2027, "matchup_period": week,
                           "team_id": team, "opponent_id": opp, "points": 0.0,
                           "opponent_points": 0.0, "is_playoff": False, "winner": "UNDECIDED",
                           "is_home": team == a})  # fmt: skip
    teams = pd.DataFrame([{"league_id": PTS, "season": 2027, "team_id": t,
                           "team_name": f"Pts {t}", "owner": f"Owner {t}", "wins": 1, "losses": 1,
                           "ties": 0, "points_for": 1200.0, "points_against": 1150.0,
                           "standing": t} for t in (1, 2, 3, 4)])  # fmt: skip
    return {"m_player_pool": pd.DataFrame(pool), "player_points": pd.DataFrame(points),
            "pro_schedule": schedule, "matchup_scores": pd.DataFrame(scores), "teams": teams,
            "m_player_profile": pd.DataFrame(columns=["league_id", "player_id"]),
            "m_transactions": pd.DataFrame(columns=["txn_date"])}  # fmt: skip


class FakeTables:
    """BigQuery stand-in: league tables by (table, league), history frames by view, and
    an in-memory finder cache that counts its writes."""

    def __init__(self):
        self.frames = {(name, CATS): f for name, f in cat_tables().items()}
        self.frames |= {(name, PTS): f for name, f in pts_tables().items()}
        self.reads, self.finder, self.finder_writes = [], {}, 0
        self.history_frames = {}

    def read(self, table, league_id):
        self.reads.append((table, league_id))
        return self.frames[(table, league_id)].copy()

    def history(self, view, league_id, start, end):
        frame = self.history_frames.get(view, pd.DataFrame(columns=["snapshot_date", "league_id"]))
        frame = frame.loc[frame["league_id"] == league_id]
        day = pd.to_datetime(frame["snapshot_date"]).dt.date
        return frame.loc[(day >= start) & (day <= end)]

    def finder_get(self, league_id, team_id, window, version):
        return self.finder.get((league_id, team_id, window, version))

    def finder_put(self, league_id, team_id, window, version, deals, now):
        self.finder_writes += 1
        self.finder[(league_id, team_id, window, version)] = deals


def league_doc(league_id, fmt, teams, **extra):
    return {"league_name": f"League {league_id}", "season": 2027, "format": fmt,
            "status": "active", "last_ingested_at": LOADED, "current_matchup_period": 3,
            "reg_season_matchup_periods": 3, "teams": [{"team_id": t, "team_name": n,
                                                        "owner": None} for t, n in teams.items()],
            **extra}  # fmt: skip


@pytest.fixture
def env(monkeypatch):
    """(client, store, tables, db): u1 manages team 1 in both leagues (commissioner of
    1001); u2 is in 1001 only, with no team picked; u3 belongs to nothing."""
    monkeypatch.setattr(services, "today", lambda: pts_fx.OPENING + dt.timedelta(days=14))
    services.SETUPS.items.clear()
    services.FRAMES.items.clear()
    db = FakeFirestore()
    leagues = db.collection("leagues")
    leagues.document(str(CATS)).set(league_doc(
        CATS, "categories", {t: f"Team {t}" for t in (1, 2, 3, 4)},
        scoring_type="H2H_MOST_CATEGORIES", categories=CAT_RECORDS))  # fmt: skip
    leagues.document(str(PTS)).set(league_doc(
        PTS, "points", {t: f"Pts {t}" for t in (1, 2, 3, 4)}, scoring_type="H2H_POINTS",
        scoring=SCORING, lineup_slots=pts_fx.SLOTS, bench_slots=pts_fx.BENCH))  # fmt: skip
    members = db.collection("members")
    members.document(f"{CATS}-u1").set({"league_id": CATS, "uid": "u1", "team_id": 1,
                                        "role": "commissioner"})  # fmt: skip
    members.document(f"{PTS}-u1").set({"league_id": PTS, "uid": "u1", "team_id": 1,
                                       "role": "member"})  # fmt: skip
    members.document(f"{CATS}-u2").set({"league_id": CATS, "uid": "u2", "team_id": None,
                                        "role": "member"})  # fmt: skip
    tables = FakeTables()
    jobs = []
    previews = {}
    store = Store(db, tables, {"season": 2027, "max_leagues": 10, "max_per_user": 3},
                  run_job=jobs.append, preview=lambda lid, season: previews[lid])  # fmt: skip
    store.jobs, store.previews = jobs, previews
    client = TestClient(create_app(store, auth.Verifier(ISSUER, AUDIENCE, keys=Keys()), env={}))
    return client, store, tables, db
