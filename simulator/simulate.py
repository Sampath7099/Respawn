"""Simulate 90 days of storefront traffic for a sample of real Steam users.

Each simulated user is driven by their real library. ~20% of it (recsys/split.py)
is their "future": games they will buy here. The rest is history, and it is all
the recommender ever saw.

Every session shows a "Picked for you" row from the user's A/B arm:
control = popularity, treatment = BPR-MF + XGBoost ranker (the real model).
A shown game that is in the user's future gets clicked (rec_click) and maybe bought.
Separately, users also find future games on their own (organic), at the same
rate in both arms. So any difference between arms comes from the model alone.

This is synthetic behaviour on top of real preferences, and the README says so.
"""
import io
import os
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "recsys"), str(ROOT / "backend")]
from app.experiment import variant  # noqa: E402
from app.recs import Recommender  # noqa: E402
from split import is_future, is_store_user  # noqa: E402

DSN = os.environ.get("RESPAWN_DSN", "postgresql://respawn:respawn@localhost:5433/respawn")
N_USERS = int(os.environ.get("SIM_USERS", 20000))
DAYS = 90
START = datetime(2026, 6, 1, tzinfo=timezone.utc)
rng = random.Random(42)


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
                       ORDER BY md5(user_id)""")
        users = [u for (u,) in cur.fetchall() if is_store_user(u)][:N_USERS]
        rec = Recommender()

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
            future = {g for g, _ in lib if is_future(uid, g)}
            past = [g for g, _ in lib if g not in future]
            if not future:
                continue
            row = rec.recommend(uid, past, v, k=30)[0]  # the home-page row for this arm
            fav = [gen for gen, games in genre_games.items() if any(g in games for g, _ in lib[:30])] or list(genre_games)
            day = signup
            bought_all = set()
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
                bought = []
                shown = [g for g in row if g not in bought_all][:10]
                hits = [g for g in shown if g in future]
                if hits and rng.random() < 0.25:  # clicks a recommendation it actually wants
                    gid = hits[0]
                    rows += [("rec_click", gid), ("add_to_cart", gid)]
                    if rng.random() < 0.7:
                        rows.append(("purchase", gid))
                        bought.append(gid)
                left = [g for g in future if g not in bought_all and g not in bought]
                if left and rng.random() < 0.12:  # organic find, same rate in both arms
                    gid = rng.choice(left)
                    rows += [("game_click", gid), ("add_to_cart", gid)]
                    if rng.random() < 0.7:
                        rows.append(("purchase", gid))
                        bought.append(gid)
                bought_all.update(bought)
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
