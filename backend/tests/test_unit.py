"""Unit tests: no database, no Kafka, no Redis."""
import json
import sys
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "recsys"))

from app.abstats import holm, two_proportion_ztest  # noqa: E402
from app.experiment import variant  # noqa: E402
from app.main import cart_hash  # noqa: E402
from app.relay import LIVE_ID_OFFSET, parse_event, publish_batch, split_batch, trending_updates  # noqa: E402
from features import FEATURE_NAMES, ranker_features  # noqa: E402
from split import is_future, is_store_user  # noqa: E402

USERS = [f"user{i}" for i in range(20000)]


# ---------------------------------------------------------------- experiment assignment
def test_variant_is_deterministic_and_balanced():
    arms = [variant(u) for u in USERS]
    assert arms == [variant(u) for u in USERS]
    assert abs(arms.count("treatment") / len(arms) - 0.5) < 0.02


def test_variant_is_independent_of_shopper_selection():
    """The bug the SRM check caught: shoppers (md5 % 4 == 0) all landed in one arm."""
    shoppers = [u for u in USERS if is_store_user(u)]
    share = sum(variant(u) == "treatment" for u in shoppers) / len(shoppers)
    assert 0.45 < share < 0.55


def test_future_split_is_about_20_percent_of_shoppers_only():
    games = range(200)
    shopper = next(u for u in USERS if is_store_user(u))
    other = next(u for u in USERS if not is_store_user(u))
    assert not any(is_future(other, g) for g in games)
    assert 0.1 < sum(is_future(shopper, g) for g in games) / 200 < 0.3


# ---------------------------------------------------------------- statistics
def test_ztest_matches_known_value():
    z, p = two_proportion_ztest(500, 1000, 550, 1000)
    assert z == pytest.approx(2.2386, abs=1e-3)
    assert p == pytest.approx(0.0252, abs=1e-3)


def test_ztest_no_difference():
    assert two_proportion_ztest(0, 10, 0, 10) == (0.0, 1.0)


def test_holm_is_monotone_and_bounded():
    adj = holm([0.01, 0.04, 0.03])
    assert adj == pytest.approx([0.03, 0.06, 0.06])
    assert all(0 <= a <= 1 for a in holm([0.9, 0.8]))


# ---------------------------------------------------------------- ranker features
def test_features_shape_names_and_scale_free_affinity():
    genre = np.array([0, 0, 1, 1, 2])
    log_pop, price = np.log1p(np.arange(5.0)), np.arange(5.0)
    cands, mf = np.array([2, 3, 4]), np.array([0.1, 0.9, 0.5])
    small = ranker_features(mf, cands, [0, 2], log_pop, price, genre, 3)
    big = ranker_features(mf, cands, [0, 0, 2, 2], log_pop, price, genre, 3)  # same mix, twice the size
    assert small.shape == (3, len(FEATURE_NAMES))
    assert list(small[:, 1]) == [2, 0, 1]  # mf_rank
    np.testing.assert_allclose(small, big)  # library size does not change any feature


# ---------------------------------------------------------------- idempotency
def test_cart_hash_ignores_order_and_duplicates():
    assert cart_hash([3, 1, 2]) == cart_hash([1, 2, 3, 3])
    assert cart_hash([1, 2]) != cart_hash([1, 2, 3])


# ---------------------------------------------------------------- relay
def event(**kw):
    e = {"event_id": 1, "user_id": "u", "event_type": "game_click", "event_ts": "2026-10-07T10:15:00+00:00",
         "variant": "control", "session_id": "s", "game_id": 5}
    return e | kw


def test_parse_event_rejects_bad_payloads():
    assert parse_event(json.dumps(event()))["game_id"] == 5
    for bad, reason in [(b"{not json", "not json"), (b"[1]", "not an object"),
                        (json.dumps(event(event_type="hack")), "unknown event_type"),
                        (json.dumps(event(session_id=None)), "missing")]:
        with pytest.raises(ValueError, match=reason):
            parse_event(bad)


class Msg:
    def __init__(self, value, error=None):
        self._v, self._e = value, error

    def value(self):
        return self._v

    def error(self):
        return self._e


def test_split_batch_sends_poison_messages_to_dead_letters():
    good, dead = split_batch([Msg(json.dumps(event()).encode()), Msg(b"\xff garbage")])
    assert len(good) == 1 and len(dead) == 1
    assert dead[0]["error"].startswith("not json")


def test_trending_buckets_by_event_time_and_weights_by_intent():
    upd = trending_updates([event(), event(event_type="purchase"), event(event_type="page_view", game_id=None),
                            event(event_ts="2026-10-07T11:01:00+00:00")])
    assert upd == {("2026-10-07T10", 5): 1 + 5, ("2026-10-07T11", 5): 1}


class FakeConn:
    """Just enough of a psycopg connection for publish_batch."""
    def __init__(self, rows):
        self.rows, self.marked = rows, []

    @contextmanager
    def transaction(self):
        yield

    def execute(self, sql, params=()):
        if sql.lstrip().startswith("UPDATE"):
            self.marked = list(params[0])
        conn = self

        class Result:
            def fetchall(self):
                return conn.rows
        return Result()


class FakeProducer:
    """Delivers every message except those whose outbox id is in `fail`."""
    def __init__(self, fail=()):
        self.fail, self.pending, self.sent = set(fail), [], []

    def produce(self, topic, key, value, on_delivery):
        self.pending.append((key, value, on_delivery))

    def flush(self, timeout):
        for key, value, cb in self.pending:
            oid = int(key.split(":")[0])
            msg = type("M", (), {"key": lambda self, k=key: k.encode()})()
            if oid in self.fail:
                cb("broker timeout", msg)
            else:
                self.sent.append(json.loads(value))
                cb(None, msg)
        self.pending = []
        return 0


def test_publish_marks_only_delivered_rows():
    from datetime import datetime, timezone
    rows = [(i, "events", {"user_id": "u", "event_type": "game_click"}, datetime(2026, 10, 7, tzinfo=timezone.utc))
            for i in (1, 2, 3)]
    conn, producer = FakeConn(rows), FakeProducer(fail={2})
    assert publish_batch(conn, producer) == (3, 2)
    assert sorted(conn.marked) == [1, 3]  # row 2 stays unpublished and is retried next batch
    assert {e["event_id"] for e in producer.sent} == {LIVE_ID_OFFSET + 1, LIVE_ID_OFFSET + 3}
