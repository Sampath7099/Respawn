"""Integration tests: the API in-process against a real Postgres + Redis.

Needs a built warehouse and a trained model. CI builds both from a small
synthetic fixture (scripts/make_fixture.py); locally they run on the full data.
"""
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.auth import issue
from app.cache import r
from app.db import pool
from app.experiment import variant
from app.main import app

USER = "76561197970982479"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth():
    return {"Authorization": f"Bearer {issue(USER)}"}


@pytest.fixture
def buyable(client, auth):
    """Fresh for-sale games the test user doesn't own yet."""
    owned = {g["game_id"] for g in client.get("/me", headers=auth).json()["library"]}
    with pool.connection() as c:
        owned |= {g for (g,) in c.execute("""SELECT oi.game_id FROM store.order_items oi
                                             JOIN store.orders o USING (order_id) WHERE o.user_id = %s""", (USER,))}
        rows = c.execute("""SELECT game_id FROM marts.dim_game WHERE price IS NOT NULL
                            ORDER BY owners DESC LIMIT 2000""").fetchall()
    free = [g for (g,) in rows if g not in owned]
    assert len(free) >= 2, "test user owns everything"
    return free


def key():
    return str(uuid.uuid4())


# ---------------------------------------------------------------- auth
def test_login_sets_httponly_cookie_and_it_authenticates(client):
    for k in r.keys("rl:login:*"):
        r.delete(k)
    res = client.post("/auth/login", json={"user_id": USER})
    assert res.status_code == 200
    cookie = res.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/me").json()["user_id"] == USER  # the cookie alone is enough
    client.post("/auth/logout")
    client.cookies.clear()
    assert client.get("/me").status_code == 401


def test_unknown_user_cannot_log_in(client):
    assert client.post("/auth/login", json={"user_id": "nobody-" + key()}).status_code == 404


def test_protected_routes_need_a_valid_token(client):
    assert client.post("/wishlist/10", headers={"Authorization": "Bearer junk"}).status_code == 401


# ---------------------------------------------------------------- catalogue
def test_catalogue_search_and_pagination(client):
    first = client.get("/games", params={"size": 5}).json()
    page2 = client.get("/games", params={"size": 5, "page": 2}).json()
    assert len(first) == 5 and {g["game_id"] for g in page2}.isdisjoint({g["game_id"] for g in first})
    word = first[0]["title"].split()[0].lower()
    assert all(word in g["title"].lower() for g in client.get("/games", params={"q": word}).json())


@pytest.mark.parametrize("params", [{"page": 0}, {"size": -1}, {"size": 1000}, {"q": "x" * 500}])
def test_bad_query_params_are_422_not_500(client, params):
    assert client.get("/games", params=params).status_code == 422


def test_missing_game_is_404(client, auth):
    assert client.get("/games/999999999").status_code == 404
    assert client.post("/wishlist/999999999", headers=auth).status_code == 404


def test_similar_games_exclude_the_game_itself(client):
    gid = client.get("/games", params={"size": 1}).json()[0]["game_id"]
    sims = client.get(f"/games/{gid}/similar").json()
    assert len(sims) == 8 and gid not in [g["game_id"] for g in sims]


# ---------------------------------------------------------------- checkout
def test_checkout_replay_returns_the_same_order(client, auth, buyable):
    h = auth | {"Idempotency-Key": key()}
    first = client.post("/checkout", headers=h, json={"game_ids": [buyable[0]]}).json()
    again = client.post("/checkout", headers=h, json={"game_ids": [buyable[0]]}).json()
    assert again == first | {"replayed": True}


def test_same_key_different_cart_is_rejected(client, auth, buyable):
    h = auth | {"Idempotency-Key": key()}
    assert client.post("/checkout", headers=h, json={"game_ids": [buyable[0]]}).status_code == 201
    assert client.post("/checkout", headers=h, json={"game_ids": [buyable[0], buyable[1]]}).status_code == 422


def test_concurrent_retries_create_exactly_one_order(client, auth, buyable):
    """A double-clicked Buy button: the same key fired 8 times at once makes one order."""
    h = auth | {"Idempotency-Key": key()}
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(lambda _: client.post("/checkout", headers=h, json={"game_ids": [buyable[0]]}).json(),
                              range(8)))
    assert len({res["order_id"] for res in results}) == 1
    assert sum(not res["replayed"] for res in results) == 1


def test_cannot_buy_a_game_already_owned(client, auth, buyable):
    assert client.post("/checkout", headers=auth | {"Idempotency-Key": key()},
                       json={"game_ids": [buyable[0]]}).status_code == 201
    assert client.post("/checkout", headers=auth | {"Idempotency-Key": key()},
                       json={"game_ids": [buyable[0]]}).status_code == 409


def test_not_for_sale_and_empty_carts_are_rejected(client, auth):
    with pool.connection() as c:
        row = c.execute("SELECT game_id FROM raw.games WHERE price IS NULL LIMIT 1").fetchone()
    if row:
        assert client.post("/checkout", headers=auth | {"Idempotency-Key": key()},
                           json={"game_ids": [row[0]]}).status_code == 400
    assert client.post("/checkout", headers=auth | {"Idempotency-Key": key()},
                       json={"game_ids": []}).status_code == 422


# ---------------------------------------------------------------- clickstream
def test_events_counts_valid_and_rejects_oversized_batches(client, auth):
    res = client.post("/events", headers=auth, json=[{"event_type": "page_view"}, {"event_type": "purchase"}])
    assert res.json() == {"accepted": 1, "rejected": 1}  # purchases only come from checkout
    assert client.post("/events", headers=auth, json=[{"event_type": "page_view"}] * 101).status_code == 413


def test_events_carry_the_client_session_id(client, auth):
    sid = "test-session-" + key()
    client.post("/events", headers=auth | {"X-Session-Id": sid}, json=[{"event_type": "page_view"}])
    with pool.connection() as c:
        n = c.execute("SELECT count(*) FROM store.outbox WHERE payload->>'session_id' = %s", (sid,)).fetchone()[0]
    assert n == 1


# ---------------------------------------------------------------- recommendations
def test_recommendations_follow_ab_arm_and_skip_owned_games(client):
    with pool.connection() as c:
        users = [u for (u,) in c.execute("""SELECT user_id FROM raw.user_items GROUP BY 1
                                            HAVING count(*) BETWEEN 20 AND 60 ORDER BY 1 LIMIT 40""")]
    seen = set()
    for uid in users:
        body = client.get("/recommendations", headers={"Authorization": f"Bearer {issue(uid)}"}).json()
        assert body["variant"] == variant(uid) and len(body["game_ids"]) == 10
        with pool.connection() as c:
            owned = {g for (g,) in c.execute("SELECT game_id FROM raw.user_items WHERE user_id = %s", (uid,))}
        assert owned.isdisjoint(body["game_ids"])
        seen.add(body["model"])
    assert seen == {"popularity", "mf+ranker"}


def test_bought_game_leaves_the_recommendation_row_immediately(client, auth):
    recs = client.get("/recommendations", headers=auth).json()["game_ids"]
    with pool.connection() as c:
        priced = {g for (g,) in c.execute("SELECT game_id FROM raw.games WHERE price IS NOT NULL AND game_id = ANY(%s)",
                                         (recs,))}
    target = next(g for g in recs if g in priced)
    assert client.post("/checkout", headers=auth | {"Idempotency-Key": key()},
                       json={"game_ids": [target]}).status_code == 201
    assert target not in client.get("/recommendations", headers=auth).json()["game_ids"]


# ---------------------------------------------------------------- misc
def test_me_returns_library_and_wishlist(client, auth, buyable):
    client.post(f"/wishlist/{buyable[-1]}", headers=auth)
    me = client.get("/me", headers=auth).json()
    assert me["user_id"] == USER and me["library_size"] > 0
    assert buyable[-1] in [g["game_id"] for g in me["wishlist"]]


def test_ab_readout_has_both_arms(client):
    r.delete("metrics:ab")
    ab = client.get("/metrics/ab").json()
    assert [a["variant"] for a in ab["arms"]] == ["control", "treatment"]
    assert ab["primary_metric"] == "buyer_rate" and 0 <= ab["p_value"] <= 1


def test_trending_endpoint_and_health(client):
    assert client.get("/games/trending").json()["window"] == "24h"
    assert client.get("/health").json()["db"] == "ok"
