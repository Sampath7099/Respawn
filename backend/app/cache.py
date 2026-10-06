"""Redis: cache-aside for hot reads, plus fixed-window rate limiting.

Redis is secondary: if it is down, reads go straight to Postgres and rate
limiting fails open, rather than taking the store down with it.
"""
import json
import logging
import os
import time

import redis

log = logging.getLogger(__name__)
r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6380/0"), decode_responses=True)


CACHE_ON = os.environ.get("CACHE", "on") == "on"  # CACHE=off for the load-test comparison


def cached(key, ttl, load):
    if not CACHE_ON:
        return load()
    try:
        hit = r.get(key)
        if hit is not None:
            return json.loads(hit)
    except redis.RedisError:
        log.warning("redis down, skipping cache")
        return load()
    value = load()
    try:
        r.setex(key, ttl, json.dumps(value, default=str))
    except redis.RedisError:
        pass
    return value


def rate_limited(scope, identity, limit, window, cost=1):
    """True if this identity used more than `limit` units in the current window."""
    key = f"rl:{scope}:{identity}:{int(time.time()) // window}"
    try:
        n = r.incrby(key, cost)
        if n == cost:
            r.expire(key, window)
        return n > limit
    except redis.RedisError:
        return False
