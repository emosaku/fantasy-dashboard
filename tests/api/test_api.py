"""Every endpoint of the API (api/), on the two fixture leagues in conftest.py. The
numbers must be the engine's own: where an endpoint wraps an analysis function, the
test calls that function directly and compares."""

import datetime as dt

import pandas as pd
import pytest

from analysis import trades as cat_trades
from api import auth, engine
from points import trades as pts_trades
from tests.api.conftest import AUDIENCE, CATS, PTS, signed, token

# --- Sign-in and access ---------------------------------------------------------------


def test_no_token_or_a_bad_one_is_refused(env):
    client, *_ = env
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer nope"}).status_code == 401
    for bad in (token(audience="someone-else"), token(issuer="https://evil.test"),
                token(minutes=-5)):  # fmt: skip
        assert client.get("/api/me", headers={"Authorization": f"Bearer {bad}"}).status_code == 401


def test_me_lists_my_leagues_and_records_the_user(env):
    client, store, _, db = env
    me = client.get("/api/me", headers=signed("u1")).json()
    assert me["user"] == {"uid": "u1", "email": "ann@example.com", "name": "U1"}
    assert [(lg["league_id"], lg["format"], lg["team_id"]) for lg in me["leagues"]] == [
        (CATS, "categories", 1), (PTS, "points", 1)]  # fmt: skip
    assert db.collection("users").document("u1").get().exists
    assert client.get("/api/leagues", headers=signed("u3")).json() == []


@pytest.mark.parametrize("path", ["", "/standings", "/players", "/trade-finder", "/luck",
                                  "/transactions", "/history?metric=standings"])  # fmt: skip
def test_a_league_you_dont_belong_to_is_403(env, path):
    client, *_ = env
    assert client.get(f"/api/leagues/{PTS}{path}", headers=signed("u2")).status_code == 403
    assert client.get(f"/api/leagues/{CATS}{path}", headers=signed("u3")).status_code == 403


def test_a_deleting_or_unloaded_league_answers_404_or_409(env):
    client, _, _, db = env
    db.collection("leagues").document(str(CATS)).set({"status": "deleting"}, merge=True)
    assert client.get(f"/api/leagues/{CATS}", headers=signed()).status_code == 404
    db.collection("leagues").document(str(CATS)).set(
        {"status": "pending", "last_ingested_at": None}, merge=True
    )
    assert client.get(f"/api/leagues/{CATS}", headers=signed()).status_code == 409


def test_recommendations_are_for_your_own_team_unless_commissioner(env):
    client, *_ = env
    # u2 has no team yet; u1 is commissioner of 1001 (any team) but not of 2002
    assert client.get(f"/api/leagues/{CATS}/trade-finder", headers=signed("u2")).status_code == 409
    assert client.get(f"/api/leagues/{CATS}/waiver-wire?team=3",
                      headers=signed("u1")).status_code == 200  # fmt: skip
    assert client.get(f"/api/leagues/{PTS}/waiver-wire?team=3",
                      headers=signed("u1")).status_code == 403  # fmt: skip
    assert client.get(f"/api/leagues/{CATS}/waiver-wire?team=9",
                      headers=signed("u1")).status_code == 404  # fmt: skip


# --- League, Overview, Matchups, Activity ---------------------------------------------


def test_league_summary_in_both_formats(env):
    client, *_ = env
    cats = client.get(f"/api/leagues/{CATS}", headers=signed()).json()
    assert cats["format"] == "categories" and len(cats["categories"]) == 9
    assert cats["windows"] == ["blended", "season"] and cats["my_team"] == 1
    assert cats["uncounted"] == []
    pts = client.get(f"/api/leagues/{PTS}", headers=signed()).json()
    assert pts["format"] == "points" and pts["lineup_slots"] == {"G": 2, "F": 2, "UT": 1}
    assert pts["uncounted"] == ["ejections (EJ)"]  # DD is counted, EJ isn't


def test_standings(env):
    client, *_ = env
    teams = client.get(f"/api/leagues/{CATS}/standings", headers=signed()).json()["teams"]
    assert [t["team_id"] for t in teams] == [1, 2, 3, 4] and teams[0]["owner"] == "Owner 1"


def test_power_rankings_categories_latest_week_and_projected_finish(env):
    client, *_ = env
    out = client.get(f"/api/leagues/{CATS}/power-rankings", headers=signed()).json()
    assert {r["matchup_period"] for r in out["rankings"]} == {2}
    assert len(out["projected_finish"]) == 4
    assert {"team_id", "projected_rank"} <= set(out["projected_finish"][0])


def test_power_rankings_points_all_play_and_projection(env):
    client, *_ = env
    out = client.get(f"/api/leagues/{PTS}/power-rankings", headers=signed()).json()
    ranks = {r["team_id"]: r for r in out["rankings"]}
    assert ranks[1]["wins"] == 2 and ranks[1]["power_rank"] == 1  # 610 and 600: top both weeks
    finish = out["projected_finish"]
    assert len(finish) == 4 and all(f["mu"] > 0 for f in finish)


def test_luck_both_formats(env):
    client, *_ = env
    cats = client.get(f"/api/leagues/{CATS}/luck", headers=signed()).json()
    assert len(cats["weeks"]) == 8
    pts = client.get(f"/api/leagues/{PTS}/luck", headers=signed()).json()
    assert len(pts["weeks"]) == 8 and len(pts["season"]) == 4


def test_matchups_and_compare(env):
    client, *_ = env
    week1 = client.get(f"/api/leagues/{CATS}/matchups?week=1", headers=signed()).json()
    assert len(week1["categories"]) == 4 * 9 and len(week1["results"]) == 4
    assert client.get(f"/api/leagues/{CATS}/matchups?week=9",
                      headers=signed()).status_code == 422  # fmt: skip
    pts = client.get(f"/api/leagues/{PTS}/matchups", headers=signed()).json()
    assert pts["week"] == 3 and len(pts["matchups"]) == 4
    both = client.get(f"/api/leagues/{CATS}/matchups/compare?a=1&b=3",
                      headers=signed()).json()  # fmt: skip
    assert {r["team_id"] for r in both["rows"]} == {1, 3}
    assert client.get(f"/api/leagues/{CATS}/matchups/compare?a=1&b=7",
                      headers=signed()).status_code == 404  # fmt: skip


def test_transactions_filter_by_date_team_and_type(env):
    client, *_ = env
    url = f"/api/leagues/{CATS}/transactions"
    assert [t["txn_id"] for t in client.get(url, headers=signed()).json()["transactions"]] == [
        "b", "a"]  # newest first  # fmt: skip
    assert [
        t["txn_id"]
        for t in client.get(f"{url}?type=trade", headers=signed()).json()["transactions"]
    ] == ["b"]
    assert [
        t["txn_id"] for t in client.get(f"{url}?team=1", headers=signed()).json()["transactions"]
    ] == ["a"]
    assert client.get(f"{url}?start=2026-10-28", headers=signed()).json()["transactions"][0][
        "txn_id"] == "b"  # fmt: skip
    assert client.get(f"/api/leagues/{PTS}/transactions",
                      headers=signed()).json()["transactions"] == []  # fmt: skip


def test_history_reads_the_snapshot_views(env):
    client, _, tables, _ = env
    tables.history_frames["v_rank_history"] = pd.DataFrame([
        {"snapshot_date": "2026-11-01", "league_id": CATS, "team_id": 1, "category": "PTS",
         "rank": 2, "rank_week_ago": 4, "rank_change": 2},
        {"snapshot_date": "2026-09-01", "league_id": CATS, "team_id": 1, "category": "PTS",
         "rank": 4, "rank_week_ago": None, "rank_change": None},
    ])  # fmt: skip
    out = client.get(f"/api/leagues/{CATS}/history", headers=signed()).json()
    assert [r["rank_change"] for r in out["rows"]] == [2]  # the last 4 weeks only
    assert client.get(f"/api/leagues/{PTS}/history?metric=category_ranks",
                      headers=signed()).status_code == 422  # fmt: skip
    assert client.get(f"/api/leagues/{CATS}/history?metric=bogus",
                      headers=signed()).status_code == 422  # fmt: skip


def test_refresh_starts_the_job_at_most_hourly(env):
    client, store, _, _ = env
    url = f"/api/leagues/{CATS}/refresh"
    leagues = store.db.collection("leagues").document(str(CATS))
    now = dt.datetime.now(dt.UTC)
    leagues.set({"last_ingested_at": now - dt.timedelta(minutes=10)}, merge=True)
    assert client.post(url, headers=signed()).status_code == 429  # data landed 10 minutes ago
    leagues.set({"last_ingested_at": now - dt.timedelta(hours=2)}, merge=True)
    assert client.post(url, headers=signed()).status_code == 202
    assert store.jobs == [CATS]
    assert client.post(url, headers=signed()).status_code == 429


# --- Players --------------------------------------------------------------------------


def test_player_rankings_categories_match_the_engine(env):
    client, store, tables, _ = env
    out = client.get(f"/api/leagues/{CATS}/players", headers=signed()).json()
    z = tables.frames[("m_player_z", CATS)]
    expected = engine.cat_rankings(z, "blended").reset_index()
    assert [p["player_id"] for p in out["players"]] == list(expected["player_id"])
    hurt = client.get(f"/api/leagues/{CATS}/players?hide_injured=true", headers=signed()).json()
    assert 102 not in [p["player_id"] for p in hurt["players"]]  # OUT
    found = client.get(f"/api/leagues/{CATS}/players?q=fa10", headers=signed()).json()
    assert {p["player_id"] for p in found["players"]} == {101, 102, 103}


def test_player_rankings_points_rank_by_fpg(env):
    client, *_ = env
    out = client.get(f"/api/leagues/{PTS}/players?window=season", headers=signed()).json()
    fpg = [p["fpg"] for p in out["players"]]
    assert fpg == sorted(fpg, reverse=True) and out["players"][0]["rank"] == 1
    assert client.get(f"/api/leagues/{PTS}/players?window=last_7",
                      headers=signed()).status_code == 422  # fmt: skip


def test_player_detail(env):
    client, *_ = env
    one = client.get(f"/api/leagues/{CATS}/players/10", headers=signed()).json()
    assert one["info"]["player_name"] == "P10" and one["health"]["avg_games_played"] == 70.0
    assert {r["stat_window"] for r in one["lines"]} == {"season", "projected"}
    assert len(one["values"]) == 2 * 9
    pts = client.get(f"/api/leagues/{PTS}/players/10", headers=signed()).json()
    assert {v["stat_window"] for v in pts["values"]} == {"season", "projected"}
    assert client.get(f"/api/leagues/{CATS}/players/999", headers=signed()).status_code == 404


def test_roster_strength_both_formats(env):
    client, store, tables, _ = env
    cats = client.get(f"/api/leagues/{CATS}/roster-strength", headers=signed()).json()
    team1 = {t["category"]: t["tier"] for t in cats["tiers"] if t["team_id"] == 1}
    assert team1["BLK"] == "Lock"  # the fixture's team 1 runs away with blocks
    assert len(cats["strength"]) == 36 and len(cats["ranks"]) == 36
    pts = client.get(f"/api/leagues/{PTS}/roster-strength", headers=signed()).json()
    assert len(pts["teams"]) == 4 and pts["teams"][0]["projected_points"] > 0
    assert {"Scoring", "Rebounds"} <= set(pts["sources"][0])


# --- Trades ---------------------------------------------------------------------------


def test_trade_finder_categories_matches_the_engine_and_is_cached(env):
    client, _, tables, _ = env
    out = client.get(f"/api/leagues/{CATS}/trade-finder", headers=signed()).json()
    players, totals = engine.cat_league(tables.frames[("m_player_z", CATS)], "blended")
    expected = cat_trades.find_trades(players, totals, 1, engine.cat_weights(totals, 1),
                                      top=engine.FINDER_TOP)  # fmt: skip
    assert len(out["deals"]) == len(expected) > 0
    first, want = out["deals"][0], expected.iloc[0]
    assert first["my_change"] == pytest.approx(want["dE_me"])
    assert first["give_ids"] == list(want["give_ids"]) and first["verdict"] in (
        "win_win", "they_say_no")  # fmt: skip
    assert first["reason"] and first["partner"].startswith("Team ")
    assert tables.finder_writes == 1
    client.get(f"/api/leagues/{CATS}/trade-finder", headers=signed())
    assert tables.finder_writes == 1  # second visit: from the cache
    custom = client.get(f"/api/leagues/{CATS}/trade-finder?delta=2.0&overrides="
                        '{"AST":"Punt"}', headers=signed())  # fmt: skip
    assert custom.status_code == 200 and tables.finder_writes == 1  # not cached
    assert client.get(f"/api/leagues/{CATS}/trade-finder?overrides=" '{"XYZ":"Punt"}',
                      headers=signed()).status_code == 422  # fmt: skip


def test_trade_finder_points_matches_the_engine(env):
    client, *_ = env
    from api.context import build
    from api.services import LeagueData

    out = client.get(f"/api/leagues/{PTS}/trade-finder", headers=signed()).json()
    store = env[1]
    ctx = build(store.league(PTS), {"team_id": 1, "role": "member"})
    expected = pts_trades.find_trades(LeagueData(store, ctx).setup("blended"), 1)
    assert len(out["deals"]) == len(expected) > 0
    assert out["deals"][0]["my_change"] == pytest.approx(expected.iloc[0]["dE_me"])
    assert out["deals"][0]["pitch"] and out["deals"][0]["change_unit"] == "expected wins a week"


def test_waiver_wire_both_formats(env):
    client, *_ = env
    cats = client.get(f"/api/leagues/{CATS}/waiver-wire", headers=signed()).json()["moves"]
    assert cats and all(m["add_id"] != 102 for m in cats)  # 102 is OUT
    assert cats[0]["reason"]
    pts = client.get(f"/api/leagues/{PTS}/waiver-wire", headers=signed()).json()["moves"]
    assert all(m["my_change"] > 0 for m in pts)


def test_mock_trade_categories_matches_simulate_trade(env):
    client, _, tables, _ = env
    move = {"partner": 2, "give": [10], "get": [20]}
    out = client.post(f"/api/leagues/{CATS}/trades/analyze", json=move, headers=signed()).json()
    z = tables.frames[("m_player_z", CATS)]
    players, totals = engine.cat_league(z, "blended")
    weights = engine.cat_weights(totals, 1)
    _, mine, theirs = cat_trades.simulate_trade(
        players,
        totals,
        1,
        2,
        [10],
        [20],
        punts_me=cat_trades.punts(weights[1]),
        punts_them=cat_trades.punts(weights[2]),
        empty=engine.cat_empty_slot(z, "blended"),
    )
    assert out["my_change"] == pytest.approx(mine.delta_e)
    assert out["their_change"] == pytest.approx(theirs.delta_e)
    assert out["verdict"] == engine.verdict(mine.delta_e, theirs.delta_e, out["lopsided"])
    assert set(out["work"]["my_categories"]) == set(totals.columns)
    pickup = client.post(
        f"/api/leagues/{CATS}/trades/analyze",
        json={"my_add": [103], "my_drop": [13]},
        headers=signed(),
    ).json()
    assert pickup["their_change"] is None and pickup["my_change"] > 0  # 103: elite STL


@pytest.mark.parametrize("move", [
    {"partner": 2, "give": [20], "get": [10]},  # players on the wrong sides
    {"partner": 1, "give": [10], "get": [11]},  # trading with yourself
    {"partner": 2},  # nothing picked
    {"my_add": [999]},  # not in the pool
    {"get": [20]},  # a free-agent move can't take their players
])  # fmt: skip
def test_mock_trade_rejects_impossible_moves(env, move):
    client, *_ = env
    assert client.post(f"/api/leagues/{CATS}/trades/analyze", json=move,
                       headers=signed()).status_code == 422  # fmt: skip


def test_mock_trade_points_matches_the_engine(env):
    client, store, *_ = env
    from api.context import build
    from api.services import LeagueData

    out = client.post(
        f"/api/leagues/{PTS}/trades/analyze",
        json={"partner": 2, "give": [10], "get": [20]},
        headers=signed(),
    ).json()
    ctx = build(store.league(PTS), {"team_id": 1, "role": "member"})
    want = pts_trades.mock(LeagueData(store, ctx).setup("blended"), 1, 2, (10,), (20,))
    assert out["my_change"] == pytest.approx(float(want["dE"][1]))
    assert out["their_change"] == pytest.approx(float(want["dE"][2]))
    assert set(out["work"]["rosters_after"]) == {"1", "2"}


def test_saved_trades_round_trip(env):
    client, *_ = env
    url = f"/api/leagues/{CATS}/saved-trades"
    saved = client.post(url, json={"partner": 2, "give": [10], "get": [20]}, headers=signed())
    assert saved.status_code == 201
    listed = client.get(url, headers=signed()).json()["trades"]
    assert [(t["id"], t["give"], t["get"]) for t in listed] == [(saved.json()["id"], [10], [20])]
    assert client.delete(f"{url}/{saved.json()['id']}", headers=signed()).status_code == 204
    assert client.get(url, headers=signed()).json()["trades"] == []


# --- Onboarding -----------------------------------------------------------------------


def test_onboarding_preview_then_register(env):
    client, store, _, db = env
    store.previews[555] = {"league_name": "New League", "format": "points", "scoring_type":
                           "H2H_POINTS", "categories": [], "scoring": [], "uncounted": [],
                           "teams": [{"team_id": 1, "team_name": "A"}], "private": False,
                           "my_team": None}  # fmt: skip
    url = "https://fantasy.espn.com/basketball/league?leagueId=555"
    found = client.post("/api/onboarding/preview", json={"league": url}, headers=signed("u3"))
    assert found.status_code == 200 and found.json()["league_id"] == 555
    bad = client.post("/api/onboarding/register-league", json={"league": "555", "team_id": 9},
                      headers=signed("u3"))  # fmt: skip
    assert bad.status_code == 422
    made = client.post("/api/onboarding/register-league", json={"league": "555", "team_id": 1},
                       headers=signed("u3"))  # fmt: skip
    assert made.status_code == 201 and made.json()["status"] == "pending"
    assert store.jobs == [555]
    assert db.collection("leagues").document("555").get().to_dict()["format"] == "points"
    again = client.post("/api/onboarding/register-league", json={"league": "555"},
                        headers=signed("u1"))  # fmt: skip
    assert again.status_code == 409  # already on League Lab
    assert client.post("/api/onboarding/preview", json={"league": "not a league"},
                       headers=signed("u3")).status_code == 422  # fmt: skip


def test_the_audience_is_what_the_web_app_signs_in_as():
    assert AUDIENCE == "league-lab-web"


def test_precompute_warms_every_team_of_every_loaded_league(env):
    from api import precompute

    _, store, tables, db = env
    db.collection("leagues").document("777").set({"status": "pending"})  # not loaded: skipped
    found = precompute.leagues(db)
    assert sorted(d["league_id"] for d in found) == [CATS, PTS]
    now = dt.datetime.now(dt.UTC)
    assert [precompute.warm(store, d, now) for d in found] == [4, 4]
    assert tables.finder_writes == 8
    assert {(k[0], k[2]) for k in tables.finder} == {(CATS, "blended"), (PTS, "blended")}


def test_local_dev_sign_in_needs_no_token_and_is_refused_on_cloud_run(env, monkeypatch):
    from api.main import create_app
    from fastapi.testclient import TestClient

    _, store, _, _ = env
    dev = TestClient(create_app(store, auth.DevVerifier("me@test"), env={}))
    assert dev.get("/api/me").json()["user"]["uid"] == "dev:me@test"
    monkeypatch.setenv("K_SERVICE", "league-lab-api")
    with pytest.raises(RuntimeError):
        auth.DevVerifier("me@test")
    assert auth.from_env({"DEV_AUTH_EMAIL": "me@test", "K_SERVICE": "x"}) is None


def test_es256_tokens_like_whops_are_accepted():
    """Whop signs ID tokens with ES256 (its discovery document says so)."""
    import jwt
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())

    class Keys:
        def get_signing_key_from_jwt(self, token):
            class Found:
                pass

            Found.key = key.public_key()
            return Found()

    now = dt.datetime.now(dt.UTC)
    claims = {"sub": "user_abc", "aud": "app_123", "iss": "https://api.whop.com", "iat": now,
              "exp": now + dt.timedelta(minutes=5), "email": "a@b.co"}  # fmt: skip
    token_ = jwt.encode(claims, key, algorithm="ES256")
    user = auth.Verifier("https://api.whop.com", "app_123", keys=Keys()).verify(token_)
    assert user.uid == "user_abc" and user.email == "a@b.co"
