"""API tests against a real Postgres + Redis (docker compose up -d postgres redis).

Needs the warehouse built (marts.dim_game) and raw.users loaded.
"""
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.main import app

USER = "76561197970982479"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth(client):
    token = client.post("/auth/login", json={"user_id": USER}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_unknown_user_cannot_log_in(client):
    assert client.post("/auth/login", json={"user_id": "nobody"}).status_code == 404


def test_catalogue_search_and_pagination(client):
    page1 = client.get("/games", params={"q": "counter", "size": 5}).json()
    assert page1 and all("counter" in g["title"].lower() for g in page1)
    page2 = client.get("/games", params={"size": 5, "page": 2}).json()
    first = client.get("/games", params={"size": 5}).json()
    assert {g["game_id"] for g in page2}.isdisjoint({g["game_id"] for g in first})


def test_missing_game_is_404(client):
    assert client.get("/games/999999999").status_code == 404


def test_protected_routes_need_a_valid_token(client):
    assert client.post("/wishlist/10", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_checkout_replay_returns_same_order(client, auth):
    gid = client.get("/games", params={"size": 1}).json()[0]["game_id"]
    h = auth | {"Idempotency-Key": str(uuid.uuid4())}
    first = client.post("/checkout", headers=h, json={"game_ids": [gid]}).json()
    again = client.post("/checkout", headers=h, json={"game_ids": [gid]}).json()
    assert again == {"order_id": first["order_id"], "replayed": True}


def test_concurrent_retries_create_exactly_one_order(client, auth):
    """A double-clicked Buy button fires the same key twice at once: one order, not two."""
    gid = client.get("/games", params={"size": 1}).json()[0]["game_id"]
    h = auth | {"Idempotency-Key": str(uuid.uuid4())}
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(lambda _: client.post("/checkout", headers=h, json={"game_ids": [gid]}).json(),
                              range(8)))
    assert len({r["order_id"] for r in results}) == 1
    assert sum(not r["replayed"] for r in results) == 1


def test_empty_cart_rejected(client, auth):
    h = auth | {"Idempotency-Key": str(uuid.uuid4())}
    assert client.post("/checkout", headers=h, json={"game_ids": []}).status_code == 400


def test_recommendations_follow_ab_arm_and_skip_owned_games(client):
    from app.db import pool
    from app.auth import issue
    from app.main import variant
    with pool.connection() as c:
        users = [u for (u,) in c.execute("""SELECT user_id FROM raw.user_items GROUP BY 1
                                            HAVING count(*) BETWEEN 20 AND 60 LIMIT 40""").fetchall()]
    seen = set()
    for uid in users:
        token = issue(uid)  # mint directly: /auth/login is rate limited to 10/min
        body = client.get("/recommendations", headers={"Authorization": f"Bearer {token}"}).json()
        assert body["variant"] == variant(uid)
        assert len(body["game_ids"]) == 10
        with pool.connection() as c:
            owned = {g for (g,) in c.execute("SELECT game_id FROM raw.user_items WHERE user_id = %s", (uid,))}
        assert owned.isdisjoint(body["game_ids"])
        seen.add(body["model"])
    assert seen == {"popularity", "mf+ranker"}


def test_me_returns_library_and_wishlist(client, auth):
    gid = client.get("/games", params={"size": 1, "page": 3}).json()[0]["game_id"]
    client.post(f"/wishlist/{gid}", headers=auth)
    me = client.get("/me", headers=auth).json()
    assert me["user_id"] == USER and me["library_size"] > 0
    assert gid in [g["game_id"] for g in me["wishlist"]]


def test_similar_games_exclude_the_game_itself(client):
    gid = client.get("/games", params={"size": 1}).json()[0]["game_id"]
    sims = client.get(f"/games/{gid}/similar").json()
    assert len(sims) == 8 and gid not in [g["game_id"] for g in sims]


def test_ab_readout_has_both_arms(client):
    ab = client.get("/metrics/ab").json()
    assert [a["variant"] for a in ab["arms"]] == ["control", "treatment"]
    assert 0 <= ab["p_value"] <= 1
