"""Outbox relay + event sink.

    python -m app.relay publish   store.outbox -> Kafka topic "events"
    python -m app.relay consume   Kafka "events" -> raw.events (the warehouse input)

Delivery is at-least-once: a crash between produce and marking a row published
re-sends it. The sink makes that harmless: event_id is derived from the outbox
id and inserted with ON CONFLICT DO NOTHING, so duplicates collapse.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

import psycopg
from confluent_kafka import Consumer, Producer

DSN = os.environ.get("RESPAWN_DSN", "postgresql://respawn:respawn@localhost:5433/respawn")
BROKERS = os.environ.get("KAFKA_BROKERS", "localhost:19092")
LIVE_ID_OFFSET = 10**12  # keeps live event ids clear of simulated ones


def publish():
    producer = Producer({"bootstrap.servers": BROKERS, "enable.idempotence": True})
    # autocommit: each conn.transaction() below is then a real, committed transaction
    # (without it the first query opens an implicit txn and every batch becomes a savepoint)
    with psycopg.connect(DSN, autocommit=True) as conn:
        # the API owns the schema; wait for it instead of crashing on a cold start
        while not conn.execute("SELECT to_regclass('store.outbox')").fetchone()[0]:
            time.sleep(2)
        while True:
            with conn.transaction():
                # SKIP LOCKED lets several relays run side by side without double-sending
                rows = conn.execute("""SELECT id, topic, payload, created_at FROM store.outbox
                                       WHERE published_at IS NULL ORDER BY id
                                       LIMIT 500 FOR UPDATE SKIP LOCKED""").fetchall()
                for oid, topic, payload, created in rows:
                    payload |= {"event_id": LIVE_ID_OFFSET + oid, "event_ts": created.isoformat()}
                    producer.produce(topic, key=payload["user_id"], value=json.dumps(payload))
                producer.flush()
                if rows:
                    conn.execute("UPDATE store.outbox SET published_at = now() WHERE id = ANY(%s)",
                                 ([r[0] for r in rows],))
                    print(f"published {len(rows)}", flush=True)
            if not rows:
                time.sleep(1)


def consume():
    consumer = Consumer({"bootstrap.servers": BROKERS, "group.id": "warehouse-sink",
                         "auto.offset.reset": "earliest", "enable.auto.commit": False})
    consumer.subscribe(["events"])
    with psycopg.connect(DSN, autocommit=True) as conn:
        while True:
            msgs = consumer.consume(500, timeout=1.0)
            batch = [json.loads(m.value()) for m in msgs if not m.error()]
            if not batch:
                continue
            with conn.cursor() as cur:
                cur.executemany("""
                    INSERT INTO raw.events (event_id, user_id, session_id, event_type, game_id, price, variant, event_ts)
                    VALUES (%(event_id)s, %(user_id)s, %(session)s, %(event_type)s, %(game_id)s, %(price)s,
                            %(variant)s, %(event_ts)s)
                    ON CONFLICT (event_id) DO NOTHING""",
                                [e | {"session": f"{e['user_id']}-{datetime.now(timezone.utc):%j%H}"} for e in batch])
            consumer.commit(asynchronous=False)  # commit only after the rows are durable
            print(f"sunk {len(batch)}", flush=True)


if __name__ == "__main__":
    {"publish": publish, "consume": consume}[sys.argv[1]]()
