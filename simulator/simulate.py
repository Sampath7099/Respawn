"""Simulate 90 days of storefront traffic for a sample of real Steam users.

Each simulated user is driven by their real library: the games they actually
own are what they eventually buy; their genre mix decides what they browse.
Funnel: page_view -> game_click -> (wishlist_add) -> add_to_cart -> purchase.
Users are bucketed into A/B variants by a stable hash of user_id.

This is synthetic behaviour on top of real preferences, and the README says so.
"""
import hashlib
import io
import os
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import psycopg

DSN = os.environ.get("RESPAWN_DSN", "postgresql://respawn:respawn@localhost:5433/respawn")
N_USERS = int(os.environ.get("SIM_USERS", 20000))
DAYS = 90
START = datetime(2026, 6, 1, tzinfo=timezone.utc)
rng = random.Random(42)


def variant(user_id):
    return "treatment" if int(hashlib.md5(user_id.encode()).hexdigest(), 16) % 2 else "control"


def main():
    with psycopg.connect(DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("""SELECT g.game_id, COALESCE(g.price, 0), gg.genre
                       FROM raw.games g JOIN raw.game_genres gg USING (game_id)""")
        price, genre_games = {}, defaultdict(list)
        for gid, p, gen in cur.fetchall():
            price[gid] = float(p)
            genre_games[gen].append(gid)

        cur.execute("""SELECT game_id, count(*) FROM raw.user_items GROUP BY 1""")
        popularity = dict(cur.fetchall())
        for gen in genre_games:  # browse popular games more often
            genre_games[gen].sort(key=lambda g: -popularity.get(g, 0))
            genre_games[gen] = genre_games[gen][:300]

        cur.execute("""SELECT user_id FROM raw.users u
                       WHERE EXISTS (SELECT 1 FROM raw.user_items i WHERE i.user_id = u.user_id)
                       ORDER BY md5(user_id) LIMIT %s""", (N_USERS,))
        users = [r[0] for r in cur.fetchall()]

        cur.execute("""SELECT i.user_id, i.game_id, i.playtime_forever FROM raw.user_items i
                       WHERE i.user_id = ANY(%s)
                         AND i.game_id IN (SELECT game_id FROM raw.games)""", (users,))
        owned = defaultdict(list)
        for uid, gid, pt in cur.fetchall():
            owned[uid].append((gid, pt))

        cur.execute("TRUNCATE raw.events")
        buf, eid, n = io.StringIO(), 0, 0
        for uid in users:
            lib = owned.get(uid)
            if not lib:
                continue
            v = variant(uid)
            signup = START + timedelta(days=rng.random() * 60)
            # activity decays over time -> realistic retention curves
            activity = rng.choice([0.05, 0.15, 0.3, 0.6])
            churn = rng.choice([0.05, 0.15, 0.35])
            to_buy = [g for g, _ in sorted(lib, key=lambda x: -x[1])][:rng.randint(1, 12)]
            rng.shuffle(to_buy)
            fav = [gen for gen, games in genre_games.items() if any(g in games for g, _ in lib[:30])] or list(genre_games)
            day = signup
            while day < START + timedelta(days=DAYS):
                sid = f"{uid}-{day:%j%H%M}"
                t = day + timedelta(hours=rng.uniform(8, 23))
                rows = [("page_view", None)]
                for _ in range(rng.randint(1, 6)):
                    gen = rng.choice(fav)
                    gid = rng.choice(genre_games[gen][:50])
                    rows.append(("game_click", gid))
                    if rng.random() < 0.08:
                        rows.append(("wishlist_add", gid))
                if to_buy and rng.random() < (0.35 if v == "treatment" else 0.30):
                    gid = to_buy.pop()
                    rows += [("game_click", gid), ("add_to_cart", gid)]
                    if rng.random() < 0.7:
                        rows.append(("purchase", gid))
                for et, gid in rows:
                    t += timedelta(seconds=rng.randint(5, 120))
                    p = price.get(gid) if gid else None
                    buf.write(f"{eid}\t{uid}\t{sid}\t{et}\t{gid if gid else chr(92)+'N'}\t"
                              f"{p if p is not None else chr(92)+'N'}\t{v}\t{t.isoformat()}\n")
                    eid += 1
                activity *= 0.97
                if rng.random() < churn:  # user leaves for good
                    break
                gap = rng.expovariate(max(activity, 0.01))
                day += timedelta(days=max(1, gap))
            n += 1
        buf.seek(0)
        with cur.copy("COPY raw.events FROM STDIN") as cp:
            cp.write(buf.read())
        print(f"simulated users={n} events={eid}")


if __name__ == "__main__":
    main()
