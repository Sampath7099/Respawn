"""Simulate 90 days of storefront traffic for real Steam users (writes raw.sim_events).

Ground truth: ~20% of each shopper's real library is their "future" (recsys/split.py),
games they genuinely want. The recommender never trains on it.

Behaviour per session (all parameters below, in one place):
- The home page shows a 10-game row from the user's A/B arm (control: popularity,
  treatment: the model). The row is recomputed after every purchase.
- Position bias: slot i is examined with probability EXAMINE / log2(i + 2).
- An examined game is clicked with P_CLICK_WANTED if it is in the user's future,
  else P_CLICK_OTHER. Clicked games can be bought: wanted ones often, others rarely
  (impulse buys). Wanted-but-not-bought clicks may be wishlisted.
- Users also find wanted games without recommendations (organic), at the same rate
  in both arms, preferring their wishlist.
- Purchase intent is higher on weekends (WEEKEND_BOOST), so demand has real weekly seasonality.

What this can and cannot show: the arms differ only through the rows they show,
so the A/B result tests the full pipeline (assignment -> serving -> events -> warehouse
-> analysis) and how offline ranking quality translates under this click model.
It is NOT evidence of real-world lift. The parameters are assumptions, not data.
"""
import io
import os
import random
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from math import log2
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

# behaviour parameters (assumptions)
EXAMINE = 0.6           # chance the top slot is looked at; decays with log2 position
P_CLICK_WANTED = 0.45   # examined + in user's future
P_CLICK_OTHER = 0.03    # examined + not wanted (curiosity)
P_BUY_WANTED = 0.6
P_BUY_OTHER = 0.05      # impulse buy
P_WISHLIST = 0.3        # wanted, clicked, not bought
P_ORGANIC = 0.10        # finds a wanted game without recommendations
WEEKEND_BOOST = 1.5

rng = random.Random(42)


def later(t):
    return t + timedelta(seconds=rng.randint(5, 120))


def main():
    with psycopg.connect(DSN, autocommit=True) as conn, conn.cursor() as cur:
        # null price = not for sale (unparseable price in the dataset): never sold here either
        price = {g: float(p) for g, p in cur.execute("SELECT game_id, price FROM raw.games WHERE price IS NOT NULL")}
        genre_games = defaultdict(list)
        for gid, gen in cur.execute("SELECT game_id, genre FROM raw.game_genres"):
            if gid in price:
                genre_games[gen].append(gid)
        popularity = dict(cur.execute("SELECT game_id, count(*) FROM raw.user_items GROUP BY 1").fetchall())
        for gen in genre_games:
            genre_games[gen] = sorted(genre_games[gen], key=lambda g: -popularity.get(g, 0))[:50]

        users = [u for (u,) in cur.execute("""SELECT user_id FROM raw.users u WHERE EXISTS
                     (SELECT 1 FROM raw.user_items i WHERE i.user_id = u.user_id) ORDER BY md5(user_id)""")
                 if is_store_user(u)][:N_USERS]
        owned = defaultdict(list)
        for uid, gid in cur.execute("SELECT user_id, game_id FROM raw.user_items WHERE user_id = ANY(%s)", (users,)):
            owned[uid].append(gid)
        rec = Recommender()

        cur.execute("TRUNCATE raw.sim_events")  # only simulated data; live events are never touched
        buf, eid, n = io.StringIO(), 0, 0

        def emit(uid, sid, et, gid, v, t):
            nonlocal eid
            p = price.get(gid) if gid else None
            buf.write(f"{eid}\t{uid}\t{sid}\t{et}\t{gid if gid else chr(92) + 'N'}\t"
                      f"{p if p is not None else chr(92) + 'N'}\t{v}\t{t.isoformat()}\n")
            eid += 1

        for uid in users:
            lib = owned[uid]
            future = {g for g in lib if is_future(uid, g) and g in price}
            if not future:
                continue
            past = [g for g in lib if g not in future]
            v = variant(uid)
            fav = [gen for gen, gs in genre_games.items() if set(gs) & set(lib)] or list(genre_games)
            activity = rng.choice([0.05, 0.15, 0.3, 0.6])
            churn = rng.choice([0.05, 0.15, 0.35])
            day = START + timedelta(days=rng.random() * 60)
            bought, wishlist = set(), []
            row = rec.recommend(uid, past, v, k=10)[0]
            while day < START + timedelta(days=DAYS):
                sid = f"{uid}-{day:%j%H%M}"
                t = day + timedelta(hours=rng.uniform(8, 23))
                boost = WEEKEND_BOOST if t.weekday() >= 5 else 1.0
                emit(uid, sid, "page_view", None, v, t)
                for _ in range(rng.randint(1, 5)):  # browsing by taste
                    t = later(t)
                    emit(uid, sid, "game_click", rng.choice(genre_games[rng.choice(fav)]), v, t)

                new_buys = []
                for pos, gid in enumerate(row):
                    if rng.random() > EXAMINE / log2(pos + 2):
                        continue
                    wanted = gid in future
                    if rng.random() > (P_CLICK_WANTED if wanted else P_CLICK_OTHER):
                        continue
                    t = later(t)
                    emit(uid, sid, "rec_click", gid, v, t)
                    if gid in price and rng.random() < min(1.0, (P_BUY_WANTED if wanted else P_BUY_OTHER) * boost):
                        t = later(t)
                        emit(uid, sid, "add_to_cart", gid, v, t)
                        t = later(t)
                        emit(uid, sid, "purchase", gid, v, t)
                        new_buys.append(gid)
                    elif wanted and gid not in wishlist and rng.random() < P_WISHLIST:
                        t = later(t)
                        emit(uid, sid, "wishlist_add", gid, v, t)
                        wishlist.append(gid)

                left = [g for g in future if g not in bought and g not in new_buys]
                if left and rng.random() < P_ORGANIC * boost:
                    wished = [g for g in wishlist if g in left]
                    gid = wished[0] if wished and rng.random() < 0.5 else rng.choice(left)
                    t = later(t)
                    emit(uid, sid, "game_click", gid, v, t)
                    t = later(t)
                    emit(uid, sid, "add_to_cart", gid, v, t)
                    t = later(t)
                    emit(uid, sid, "purchase", gid, v, t)
                    new_buys.append(gid)

                if new_buys:  # refresh the row: bought games leave it
                    bought.update(new_buys)
                    row = rec.recommend(uid, past + list(bought), v, k=10)[0]
                activity *= 0.97
                if rng.random() < churn:
                    break
                day += timedelta(days=max(1, rng.expovariate(max(activity, 0.01))))
            n += 1
        buf.seek(0)
        with cur.copy("COPY raw.sim_events FROM STDIN") as cp:
            cp.write(buf.read())
        print(f"simulated users={n} events={eid}")


if __name__ == "__main__":
    main()
