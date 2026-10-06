"""Respawn storefront API.

Reads (catalogue, game pages, recommendations) go through Redis cache-aside.
Writes (wishlist, checkout, clickstream) append to store.outbox in the same
transaction, and app/relay.py ships the outbox to Kafka.
"""
import hashlib
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import redis
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from app.abstats import two_proportion_ztest
from app.auth import COOKIE, TTL, current_user, issue
from app.cache import cached, r, rate_limited
from app.db import pool
from app.experiment import EXPERIMENT, variant

SCHEMA = Path(__file__).resolve().parent.parent / "schema.sql"
REC_POOL = 50  # recommendations are cached per user as a top-50, sliced per request


@asynccontextmanager
async def lifespan(_):
    pool.open()
    with pool.connection() as c, c.transaction():
        # every uvicorn worker runs this on boot; the advisory lock serialises the DDL
        c.execute("SELECT pg_advisory_xact_lock(hashtext('respawn-schema'))")
        c.execute(SCHEMA.read_text())
    try:  # load the model at boot, not on the first request (that request would wait seconds)
        get_recommender()
    except FileNotFoundError:
        pass  # no trained model yet: /recommendations fails, the rest of the store works
    yield
    pool.close()


app = FastAPI(title="Respawn API", lifespan=lifespan)


def emit(cur, user_id, event_type, game_id=None, price=None, session_id=None):
    cur.execute("INSERT INTO store.outbox (topic, payload) VALUES ('events', %s)",
                (Jsonb({"user_id": user_id, "event_type": event_type, "game_id": game_id,
                        "price": float(price) if price is not None else None,
                        "variant": variant(user_id), "session_id": session_id or f"{user_id}-server"}),))


def owned_games(conn, user):
    """Steam library + everything bought here."""
    return [g for (g,) in conn.execute("""
        SELECT game_id FROM raw.user_items WHERE user_id = %(u)s
        UNION SELECT oi.game_id FROM store.order_items oi JOIN store.orders o USING (order_id)
        WHERE o.user_id = %(u)s""", {"u": user}).fetchall()]


def games_by_id(ids):
    """Game cards for a list of ids, in the given order."""
    if not ids:
        return []
    with pool.connection() as c, c.cursor(row_factory=dict_row) as cur:
        rows = cur.execute("""SELECT game_id, title, price, primary_genre, owners, sentiment
                              FROM marts.dim_game WHERE game_id = ANY(%s)""", (list(ids),)).fetchall()
    by_id = {g["game_id"]: g for g in rows}
    return [by_id[i] for i in ids if i in by_id]


# ---------------------------------------------------------------- auth
class Login(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)


@app.post("/auth/login")
def login(body: Login, request: Request, response: Response):
    # client.host is the real client IP: uvicorn runs with --proxy-headers behind nginx
    if rate_limited("login", request.client.host, 10, 60):
        raise HTTPException(429, "too many login attempts")
    with pool.connection() as c:
        if not c.execute("SELECT 1 FROM raw.users WHERE user_id = %s", (body.user_id,)).fetchone():
            raise HTTPException(404, "unknown user")
    token = issue(body.user_id)
    response.set_cookie(COOKIE, token, max_age=TTL, httponly=True, samesite="strict",
                        secure=request.url.scheme == "https")
    return {"user_id": body.user_id, "variant": variant(body.user_id), "token": token}


@app.post("/auth/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(COOKIE)


# ---------------------------------------------------------------- catalogue
@app.get("/games")
def list_games(q: str | None = Query(None, max_length=100), genre: str | None = Query(None, max_length=50),
               page: int = Query(1, ge=1, le=1000), size: int = Query(24, ge=1, le=100)):
    def load():
        with pool.connection() as c, c.cursor(row_factory=dict_row) as cur:
            return cur.execute("""
                SELECT game_id, title, price, primary_genre, owners, sentiment
                FROM marts.dim_game
                WHERE (%(q)s::text IS NULL OR lower(title) LIKE '%%' || lower(%(q)s) || '%%')
                  AND (%(genre)s::text IS NULL OR genres LIKE '%%' || %(genre)s || '%%')
                ORDER BY owners DESC, game_id
                LIMIT %(size)s OFFSET %(off)s""",
                               {"q": q, "genre": genre, "size": size, "off": (page - 1) * size}).fetchall()
    return cached(f"games:{q}:{genre}:{page}:{size}", 300, load)


@app.get("/games/trending")
def trending(k: int = Query(10, ge=1, le=50)):
    """Last 24h of weighted interactions, maintained by the Kafka 'trending' consumer."""
    now = datetime.now(timezone.utc)
    keys = [f"trending:{(now - timedelta(hours=h)):%Y-%m-%dT%H}" for h in range(24)]
    try:
        r.zunionstore("trending:24h", keys)
        ids = [int(g) for g in r.zrevrange("trending:24h", 0, k - 1)]
    except redis.RedisError:
        ids = []
    return {"window": "24h", "games": games_by_id(ids)}


@app.get("/games/{game_id}")
def game(game_id: int):
    def load():
        with pool.connection() as c, c.cursor(row_factory=dict_row) as cur:
            return cur.execute("SELECT * FROM marts.dim_game WHERE game_id = %s", (game_id,)).fetchone()
    g = cached(f"game:{game_id}", 3600, load)
    if not g:
        raise HTTPException(404, "game not found")
    return g


@app.get("/games/{game_id}/similar")
def similar(game_id: int):
    return cached(f"similar:{game_id}", 3600, lambda: games_by_id(get_recommender().similar(game_id)))


# ---------------------------------------------------------------- user actions
@app.post("/wishlist/{game_id}", status_code=201)
def add_wishlist(game_id: int, user=Depends(current_user), x_session_id: str | None = Header(None)):
    with pool.connection() as c, c.cursor() as cur:
        if not cur.execute("SELECT 1 FROM raw.games WHERE game_id = %s", (game_id,)).fetchone():
            raise HTTPException(404, "game not found")
        cur.execute("INSERT INTO store.wishlist (user_id, game_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (user, game_id))
        if cur.rowcount:
            emit(cur, user, "wishlist_add", game_id, session_id=x_session_id)
    return {"ok": True}


class Checkout(BaseModel):
    game_ids: list[int] = Field(min_length=1, max_length=50)


def cart_hash(game_ids):
    return hashlib.sha256(json.dumps(sorted(set(game_ids))).encode()).hexdigest()


@app.post("/checkout", status_code=201)
def checkout(body: Checkout, user=Depends(current_user),
             idempotency_key: str = Header(..., min_length=8, max_length=100),
             x_session_id: str | None = Header(None)):
    """Idempotent: replaying a key returns the original order. Reusing a key for a
    different cart is a client bug and gets 422 instead of silently returning the old order."""
    ids, h = sorted(set(body.game_ids)), cart_hash(body.game_ids)
    with pool.connection() as c, c.cursor() as cur:
        prices = dict(cur.execute("SELECT game_id, price FROM raw.games WHERE game_id = ANY(%s)", (ids,)).fetchall())
        if len(prices) != len(ids):
            raise HTTPException(400, "unknown game in cart")
        if any(p is None for p in prices.values()):
            raise HTTPException(400, "a game in the cart is not for sale")
        total = sum(prices.values())
        cur.execute("""INSERT INTO store.orders (user_id, idempotency_key, request_hash, total)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (user_id, idempotency_key) DO NOTHING RETURNING order_id""",
                    (user, idempotency_key, h, total))
        row = cur.fetchone()
        if row is None:  # this key was used before: replay or misuse
            oid, old_hash, old_total = cur.execute(
                "SELECT order_id, request_hash, total FROM store.orders WHERE user_id = %s AND idempotency_key = %s",
                (user, idempotency_key)).fetchone()
            if old_hash != h:
                raise HTTPException(422, "Idempotency-Key was already used for a different cart")
            return {"order_id": oid, "total": float(old_total), "game_ids": ids, "replayed": True}
        already = set(ids) & set(owned_games(c, user))
        if already:
            c.rollback()
            raise HTTPException(409, f"already owned: {sorted(already)}")
        for gid in ids:
            cur.execute("INSERT INTO store.order_items VALUES (%s, %s, %s)", (row[0], gid, prices[gid]))
            emit(cur, user, "purchase", gid, prices[gid], session_id=x_session_id)
    try:
        r.delete(f"recs:{user}")  # bought games must leave the recommendation row now, not in 10 min
    except redis.RedisError:
        pass
    return {"order_id": row[0], "total": float(total), "game_ids": ids, "replayed": False}


class Event(BaseModel):
    event_type: str = Field(max_length=32)
    game_id: int | None = None


CLIENT_EVENTS = {"page_view", "game_click", "rec_click", "add_to_cart"}


@app.post("/events", status_code=202)
def track(events: list[Event], user=Depends(current_user),
          x_session_id: str | None = Header(None, max_length=100)):
    """Clickstream from the frontend, batched. Rate limit counts events, not requests."""
    if len(events) > 100:
        raise HTTPException(413, "at most 100 events per batch")
    if rate_limited("events", user, 600, 60, cost=max(len(events), 1)):
        raise HTTPException(429, "slow down")
    valid = [e for e in events if e.event_type in CLIENT_EVENTS]
    with pool.connection() as c, c.cursor() as cur:
        for e in valid:
            emit(cur, user, e.event_type, e.game_id, session_id=x_session_id)
    return {"accepted": len(valid), "rejected": len(events) - len(valid)}


@app.get("/me")
def me(user=Depends(current_user)):
    with pool.connection() as c:
        library = owned_games(c, user)
        wishlist = [g for (g,) in c.execute(
            "SELECT game_id FROM store.wishlist WHERE user_id = %s ORDER BY added_at DESC", (user,)).fetchall()]
    return {"user_id": user, "variant": variant(user), "library": games_by_id(library)[:200],
            "library_size": len(library), "wishlist": games_by_id(wishlist)}


# ---------------------------------------------------------------- recommendations
recommender = None


def get_recommender():
    global recommender
    if recommender is None:  # lazy: the API still boots before a model is trained
        from app.recs import Recommender
        recommender = Recommender()
    return recommender


@app.get("/recommendations")
def recommendations(k: int = Query(10, ge=1, le=REC_POOL), user=Depends(current_user)):
    """The A/B-tested home-page row. Invalidated on checkout."""
    v = variant(user)

    def load():
        with pool.connection() as c:
            owned = owned_games(c, user)
        ids, model = get_recommender().recommend(user, owned, v, REC_POOL)
        return {"variant": v, "model": model, "game_ids": ids}
    res = cached(f"recs:{user}", 600, load)
    ids = res["game_ids"][:k]
    return {"experiment": EXPERIMENT, "variant": res["variant"], "model": res["model"],
            "game_ids": ids, "games": games_by_id(ids)}


# ---------------------------------------------------------------- metrics
@app.get("/metrics/kpis")
def kpis():
    def load():
        with pool.connection() as c, c.cursor(row_factory=dict_row) as cur:
            return cur.execute("""SELECT date_day, dau, sessions, orders, gmv
                                  FROM marts.agg_daily_kpis ORDER BY date_day""").fetchall()
    return cached("metrics:kpis", 300, load)


@app.get("/metrics/ab")
def ab():
    """Live readout of the pre-registered primary metric: share of users who bought (per user)."""
    def load():
        with pool.connection() as c, c.cursor(row_factory=dict_row) as cur:
            arms = cur.execute("""
                SELECT u.variant, count(DISTINCT u.user_id) AS users,
                       count(DISTINCT o.user_id) AS buyers,
                       coalesce(sum(o.revenue), 0)::float AS revenue
                FROM marts.dim_user u LEFT JOIN marts.fct_orders o USING (user_id)
                GROUP BY 1 ORDER BY 1""").fetchall()
        if len(arms) != 2:
            return {"experiment": EXPERIMENT, "arms": arms}
        a, b = arms  # control, treatment
        z, p = two_proportion_ztest(a["buyers"], a["users"], b["buyers"], b["users"])
        for arm in arms:
            arm["buyer_rate"] = arm["buyers"] / arm["users"]
            arm["revenue_per_user"] = arm["revenue"] / arm["users"]
        return {"experiment": EXPERIMENT, "primary_metric": "buyer_rate", "arms": arms,
                "lift": b["buyer_rate"] / a["buyer_rate"] - 1, "z": z, "p_value": p}
    return cached("metrics:ab", 300, load)


@app.get("/health")
def health():
    with pool.connection() as c:
        c.execute("SELECT 1")
    try:
        redis_ok = bool(r.ping())
    except redis.RedisError:
        redis_ok = False
    return {"db": "ok", "redis": "ok" if redis_ok else "down"}
