"""Postgres connection pool for the API (one pool per process, opened at startup)."""
import os

from psycopg_pool import ConnectionPool

DSN = os.environ.get("RESPAWN_DSN", "postgresql://respawn:respawn@localhost:5433/respawn")
pool = ConnectionPool(DSN, min_size=2, max_size=int(os.environ.get("POOL_SIZE", 10)), open=False)
