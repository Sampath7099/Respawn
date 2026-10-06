"""Outbox relay and Kafka consumers.

    python -m app.relay publish    store.outbox -> topic "events"
    python -m app.relay warehouse  "events" -> raw.events (warehouse input)
    python -m app.relay trending   "events" -> Redis "trending now" counters

Why Kafka and not a direct INSERT: one event stream, several independent readers
(warehouse sink, trending counters) that fail, lag and replay separately, without
the API knowing they exist.

Guarantees
- publish: a row is marked published only after Kafka confirms delivery of that row.
  Undelivered rows stay unpublished and are retried, so delivery is at-least-once.
- warehouse: event_id comes from the outbox id and inserts use ON CONFLICT DO NOTHING,
  so redelivered events collapse. Offsets are committed only after rows are written.
  A message that can't be parsed or validated goes to "events.dlq" with the reason,
  instead of crashing the consumer or being skipped silently.
"""
import json
import os
import sys
import time

import psycopg
from confluent_kafka import Consumer, KafkaError, Producer

DSN = os.environ.get("RESPAWN_DSN", "postgresql://respawn:respawn@localhost:5433/respawn")
BROKERS = os.environ.get("KAFKA_BROKERS", "localhost:19092")
LIVE_ID_OFFSET = 10**12  # live event ids never collide with simulated ones
EVENT_TYPES = {"page_view", "game_click", "rec_click", "wishlist_add", "add_to_cart", "purchase"}
TRENDING_WEIGHT = {"game_click": 1, "rec_click": 1, "wishlist_add": 2, "add_to_cart": 3, "purchase": 5}
REQUIRED = ("event_id", "user_id", "event_type", "event_ts", "variant", "session_id")


# ---------------------------------------------------------------- publish
def publish_batch(conn, producer, limit=500, timeout=10.0):
    """Send one batch from the outbox. Returns (sent, delivered)."""
    delivered = []

    def on_delivery(err, msg):
        if err is None:
            delivered.append(int(msg.key().decode().split(":")[0]))

    with conn.transaction():
        # SKIP LOCKED: several relays can run side by side without sending a row twice
        rows = conn.execute("""SELECT id, topic, payload, created_at FROM store.outbox
                               WHERE published_at IS NULL ORDER BY id
                               LIMIT %s FOR UPDATE SKIP LOCKED""", (limit,)).fetchall()
        for oid, topic, payload, created in rows:
            payload |= {"event_id": LIVE_ID_OFFSET + oid, "event_ts": created.isoformat()}
            # key: outbox id (for delivery tracking) + user (keeps a user's events ordered in a partition)
            producer.produce(topic, key=f"{oid}:{payload['user_id']}", value=json.dumps(payload),
                             on_delivery=on_delivery)
        producer.flush(timeout)
        if delivered:
            conn.execute("UPDATE store.outbox SET published_at = now() WHERE id = ANY(%s)", (delivered,))
    return len(rows), len(delivered)


def publish():
    producer = Producer({"bootstrap.servers": BROKERS, "enable.idempotence": True})
    with psycopg.connect(DSN, autocommit=True) as conn:  # autocommit: conn.transaction() is a real txn
        while not conn.execute("SELECT to_regclass('store.outbox')").fetchone()[0]:
            time.sleep(2)  # the API creates the schema
        while True:
            sent, ok = publish_batch(conn, producer)
            if sent:
                print(f"published {ok}/{sent}" + ("" if ok == sent else " (rest retried)"), flush=True)
            if not sent or ok < sent:
                time.sleep(1)


# ---------------------------------------------------------------- consume
def parse_event(raw):
    """Message bytes -> validated event dict, or raise ValueError with the reason."""
    try:
        e = json.loads(raw)
    except (TypeError, ValueError) as err:
        raise ValueError(f"not json: {err}") from None
    if not isinstance(e, dict):
        raise ValueError("not an object")
    missing = [f for f in REQUIRED if e.get(f) in (None, "")]
    if missing:
        raise ValueError(f"missing {missing}")
    if e["event_type"] not in EVENT_TYPES:
        raise ValueError(f"unknown event_type {e['event_type']!r}")
    e.setdefault("game_id", None)
    e.setdefault("price", None)
    return e


def split_batch(msgs):
    """Kafka messages -> (valid events, dead letters). Partition EOF is not an error."""
    good, dead = [], []
    for m in msgs:
        if m.error():
            if m.error().code() == KafkaError._PARTITION_EOF:
                continue
            raise RuntimeError(m.error())  # broker-level error: crash and let the restart policy retry
        try:
            good.append(parse_event(m.value()))
        except ValueError as err:
            dead.append({"error": str(err), "raw": m.value().decode("utf-8", "replace")})
    return good, dead


def consume(group, handle):
    consumer = Consumer({"bootstrap.servers": BROKERS, "group.id": group,
                         "auto.offset.reset": "earliest", "enable.auto.commit": False})
    dlq = Producer({"bootstrap.servers": BROKERS})
    consumer.subscribe(["events"])
    while True:
        msgs = consumer.consume(500, timeout=1.0)
        if not msgs:
            continue
        good, dead = split_batch(msgs)
        for d in dead:
            dlq.produce("events.dlq", value=json.dumps(d | {"consumer": group}))
        if dead:
            if dlq.flush(10):
                raise RuntimeError("could not write to the dead-letter topic")
            print(f"{group}: {len(dead)} message(s) -> events.dlq", flush=True)
        if good:
            handle(good)
        consumer.commit(asynchronous=False)  # only after the batch is durable
        print(f"{group}: handled {len(good)}", flush=True)


def warehouse():
    conn = psycopg.connect(DSN, autocommit=True)

    def handle(batch):
        with conn.cursor() as cur:
            cur.executemany("""
                INSERT INTO raw.events (event_id, user_id, session_id, event_type, game_id, price, variant, event_ts)
                VALUES (%(event_id)s, %(user_id)s, %(session_id)s, %(event_type)s, %(game_id)s, %(price)s,
                        %(variant)s, %(event_ts)s)
                ON CONFLICT (event_id) DO NOTHING""", batch)
    consume("warehouse-sink", handle)


def trending_updates(batch):
    """Events -> {(hour_bucket, game_id): weight}. Pure, so it is unit-tested."""
    out = {}
    for e in batch:
        w = TRENDING_WEIGHT.get(e["event_type"])
        if w and e.get("game_id"):
            key = (e["event_ts"][:13], int(e["game_id"]))  # hour bucket from event time, not arrival time
            out[key] = out.get(key, 0) + w
    return out


def trending():
    from app.cache import r

    def handle(batch):
        pipe = r.pipeline()
        for (hour, gid), w in trending_updates(batch).items():
            pipe.zincrby(f"trending:{hour}", w, gid)
            pipe.expire(f"trending:{hour}", 26 * 3600)
        pipe.execute()
    consume("trending", handle)


if __name__ == "__main__":
    {"publish": publish, "warehouse": warehouse, "trending": trending}[sys.argv[1]]()
