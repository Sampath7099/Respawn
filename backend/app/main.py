"""Respawn storefront API.

Reads (catalogue, game page) go through Redis cache-aside. Writes (wishlist,
checkout, clickstream) also append to store.outbox in the same transaction;
relay.py ships the outbox to Kafka.
"""
import hashlib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from app.auth import current_user, issue
from app.cache import cached, r, rate_limited
from app.db import pool

SCHEMA = Path(__file__).resolve().parent.parent / "schema.sql"


@asynccontextmanager
async def lifespan(_):
    pool.open()
    with pool.connection() as c:
        c.execute(SCHEMA.read_text())
    yield
    pool.close()


app = FastAPI(title="Respawn API", lifespan=lifespan)


def variant(user_id):
    """Same hash as the simulator, so A/B buckets match across systems."""
    return "treatment" if int(hashlib.md5(user_id.encode()).hexdigest(), 16) % 2 else "control"


def emit(cur, user_id, event_type, game_id=None, price=None):
    cur.execute("INSERT INTO store.outbox (topic, payload) VALUES ('events', %s)",
                (Jsonb({"user_id": user_id, "event_type": event_type, "game_id": game_id,
                        "price": float(price) if price is not None else None,
                        "variant": variant(user_id)}),))


class Login(BaseModel):
    user_id: str


@app.post("/auth/login")
def login(body: Login, request: Request):
    if rate_limited("login", request.client.host, 10, 60):
        raise HTTPException(429, "too many login attempts")
    with pool.connection() as c:
        if not c.execute("SELECT 1 FROM raw.users WHERE user_id = %s", (body.user_id,)).fetchone():
            raise HTTPException(404, "unknown user")
    return {"token": issue(body.user_id), "variant": variant(body.user_id)}


@app.get("/games")
def list_games(q: str | None = None, genre: str | None = None, page: int = 1, size: int = 24):
    size = min(size, 100)

    def load():
        with pool.connection() as c, c.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT game_id, title, price, primary_genre, owners, sentiment
                FROM marts.dim_game
                WHERE (%(q)s::text IS NULL OR lower(title) LIKE '%%' || lower(%(q)s) || '%%')
                  AND (%(genre)s::text IS NULL OR genres LIKE '%%' || %(genre)s || '%%')
                ORDER BY owners DESC, game_id
                LIMIT %(size)s OFFSET %(off)s""",
                        {"q": q, "genre": genre, "size": size, "off": (page - 1) * size})
            return cur.fetchall()
    return cached(f"games:{q}:{genre}:{page}:{size}", 300, load)


@app.get("/games/{game_id}")
def game(game_id: int):
    def load():
        with pool.connection() as c, c.cursor(row_factory=dict_row) as cur:
            return cur.execute("SELECT * FROM marts.dim_game WHERE game_id = %s", (game_id,)).fetchone()
    g = cached(f"game:{game_id}", 3600, load)
    if not g:
        raise HTTPException(404, "game not found")
    return g


@app.post("/wishlist/{game_id}", status_code=201)
def add_wishlist(game_id: int, user=Depends(current_user)):
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("INSERT INTO store.wishlist (user_id, game_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (user, game_id))
        if cur.rowcount:
            emit(cur, user, "wishlist_add", game_id)
    return {"ok": True}


class Checkout(BaseModel):
    game_ids: list[int]


@app.post("/checkout", status_code=201)
def checkout(body: Checkout, user=Depends(current_user), idempotency_key: str = Header(...)):
    """Idempotent: the same Idempotency-Key returns the original order, never a second charge."""
    if not body.game_ids:
        raise HTTPException(400, "cart is empty")
    with pool.connection() as c, c.cursor() as cur:
        prices = dict(cur.execute("SELECT game_id, coalesce(price, 0) FROM raw.games WHERE game_id = ANY(%s)",
                                  (body.game_ids,)).fetchall())
        if len(prices) != len(set(body.game_ids)):
            raise HTTPException(400, "unknown game in cart")
        cur.execute("""INSERT INTO store.orders (user_id, idempotency_key, total) VALUES (%s, %s, %s)
                       ON CONFLICT (user_id, idempotency_key) DO NOTHING RETURNING order_id""",
                    (user, idempotency_key, sum(prices.values())))
        row = cur.fetchone()
        if row is None:  # replay of a request we already processed
            oid = cur.execute("SELECT order_id FROM store.orders WHERE user_id = %s AND idempotency_key = %s",
                              (user, idempotency_key)).fetchone()[0]
            return {"order_id": oid, "replayed": True}
        for gid, p in prices.items():
            cur.execute("INSERT INTO store.order_items VALUES (%s, %s, %s)", (row[0], gid, p))
            emit(cur, user, "purchase", gid, p)
    return {"order_id": row[0], "total": float(sum(prices.values())), "replayed": False}


class Event(BaseModel):
    event_type: str
    game_id: int | None = None


@app.post("/events", status_code=202)
def track(events: list[Event], user=Depends(current_user)):
    """Clickstream from the frontend (page_view, game_click, add_to_cart)."""
    if rate_limited("events", user, 300, 60):
        raise HTTPException(429, "slow down")
    allowed = {"page_view", "game_click", "add_to_cart"}
    with pool.connection() as c, c.cursor() as cur:
        for e in events:
            if e.event_type in allowed:
                emit(cur, user, e.event_type, e.game_id)
    return {"accepted": len(events)}


recommender = None


@app.get("/recommendations")
def recommendations(k: int = 10, user=Depends(current_user)):
    """A/B-tested home-page row. Cached per user for 10 min (precomputed-feature style)."""
    global recommender
    if recommender is None:  # lazy load: the API still boots if no model is trained yet
        from app.recs import Recommender
        recommender = Recommender()
    v = variant(user)

    def load():
        with pool.connection() as c:
            owned = [g for (g,) in c.execute("""SELECT game_id FROM raw.user_items WHERE user_id = %s
                                               UNION SELECT oi.game_id FROM store.order_items oi
                                               JOIN store.orders o USING (order_id) WHERE o.user_id = %s""",
                                              (user, user)).fetchall()]
        games, model = recommender.recommend(user, owned, v, k)
        return {"variant": v, "model": model, "game_ids": games}
    return cached(f"recs:{user}:{k}", 600, load)


@app.get("/health")
def health():
    with pool.connection() as c:
        c.execute("SELECT 1")
    return {"db": "ok", "redis": "ok" if r.ping() else "down"}
