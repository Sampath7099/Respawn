"""Load the UCSD Steam dataset into Postgres `raw` schema.

The source files are Python-literal dicts (not strict JSON), so each line is
parsed with ast.literal_eval. Rows that fail validation are counted and skipped.
"""
import ast
import gzip
import io
import os
import sys
from pathlib import Path

import psycopg

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
DSN = os.environ.get("RESPAWN_DSN", "postgresql://respawn:respawn@localhost:5433/respawn")


def read_lines(name):
    with gzip.open(RAW / name, "rt", encoding="utf-8") as f:
        for line in f:
            try:
                yield ast.literal_eval(line)
            except (ValueError, SyntaxError):
                yield None


def copy_rows(cur, table, cols, rows):
    buf = io.StringIO()
    for r in rows:
        buf.write("\t".join("\\N" if v is None else str(v).replace("\\", "\\\\")
                            .replace("\t", " ").replace("\n", " ").replace("\r", " ") for v in r) + "\n")
    buf.seek(0)
    with cur.copy(f"COPY {table} ({','.join(cols)}) FROM STDIN") as cp:
        cp.write(buf.read())


def to_price(p):
    return p if isinstance(p, (int, float)) else (0.0 if p and "free" in str(p).lower() else None)


def main():
    with psycopg.connect(DSN, autocommit=True) as conn, conn.cursor() as cur:
        # the dataset is static: with --if-empty (used by the bootstrap DAG) a loaded DB is left alone
        if "--if-empty" in sys.argv and cur.execute("SELECT to_regclass('raw.games')").fetchone()[0]                 and cur.execute("SELECT count(*) FROM raw.games").fetchone()[0]:
            print("raw dataset already loaded, skipping")
            return
        cur.execute(open(Path(__file__).parent / "raw_schema.sql").read())
        # the storefront's tables are a dbt source too, so make sure they exist (same DDL the API runs)
        with conn.transaction():
            cur.execute("SELECT pg_advisory_xact_lock(hashtext('respawn-schema'))")
            cur.execute((Path(__file__).resolve().parents[1] / "backend" / "schema.sql").read_text())

        games, genres, bad = [], [], 0
        for g in read_lines("steam_games.json.gz"):
            if not g or not g.get("id"):
                bad += 1
                continue
            gid = int(g["id"])
            games.append((gid, g.get("app_name") or g.get("title"), g.get("developer"),
                          g.get("publisher"), g.get("release_date"), to_price(g.get("price")),
                          g.get("sentiment"), bool(g.get("early_access"))))
            for gen in set(g.get("genres") or []):
                genres.append((gid, gen))
        games = list({r[0]: r for r in games}.values())
        genres = list(set(genres))
        copy_rows(cur, "raw.games", ["game_id", "title", "developer", "publisher",
                                      "release_date_text", "price", "sentiment", "early_access"], games)
        copy_rows(cur, "raw.game_genres", ["game_id", "genre"], genres)
        print(f"games={len(games)} genres={len(genres)} skipped={bad}")

        users, items, bad = [], [], 0
        for u in read_lines("australian_users_items.json.gz"):
            if not u or not u.get("user_id"):
                bad += 1
                continue
            users.append((u["user_id"],))
            for it in u.get("items") or []:
                items.append((u["user_id"], int(it["item_id"]), int(it.get("playtime_forever") or 0),
                              int(it.get("playtime_2weeks") or 0)))
        users = list({r[0]: r for r in users}.values())
        items = list({(r[0], r[1]): r for r in items}.values())
        copy_rows(cur, "raw.users", ["user_id"], users)
        copy_rows(cur, "raw.user_items", ["user_id", "game_id", "playtime_forever", "playtime_2weeks"], items)
        print(f"users={len(users)} user_items={len(items)} skipped={bad}")

        reviews, bad = [], 0
        for u in read_lines("australian_user_reviews.json.gz"):
            if not u:
                bad += 1
                continue
            for r in u.get("reviews") or []:
                reviews.append((u["user_id"], int(r["item_id"]), bool(r.get("recommend")),
                                r.get("posted"), (r.get("review") or "")[:2000]))
        copy_rows(cur, "raw.reviews", ["user_id", "game_id", "recommend", "posted_text", "review_text"], reviews)
        print(f"reviews={len(reviews)} skipped={bad}")

        # serving reads a user's library by user_id; without this it is a 5M-row seq scan
        cur.execute("CREATE INDEX ON raw.user_items (user_id)")
        cur.execute("ANALYZE raw.user_items")


if __name__ == "__main__":
    main()
