"""Write a small synthetic dataset in the same format as the UCSD Steam files.

CI uses it to run the real pipeline end to end (ingest -> dbt -> train -> simulate
-> dbt -> tests) in minutes, without downloading 80 MB. Users have genre tastes,
so the recommender has real structure to learn.

    python scripts/make_fixture.py [out_dir]   (default: data/raw)
"""
import gzip
import random
import sys
from pathlib import Path

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "data" / "raw")
GENRES = ["Action", "RPG", "Strategy", "Simulation", "Adventure", "Racing"]
N_GAMES, N_USERS = 150, 500
rng = random.Random(7)


def write(name, rows):
    OUT.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT / name, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(repr(r) + "\n")  # the real files are Python literals, not JSON


games = []
for i in range(N_GAMES):
    price = rng.choice([0.0, 4.99, 9.99, 14.99, 19.99, 29.99, 59.99])
    if i % 25 == 0:
        price = "Install Now"  # unparseable price -> not for sale, like the real data
    games.append({"id": str(1000 + i), "app_name": f"Game {i}", "title": f"Game {i}", "developer": "Fixture Studio",
                  "publisher": "Fixture", "release_date": f"201{i % 9}-0{1 + i % 9}-1{i % 9}", "price": price,
                  "genres": [GENRES[i % len(GENRES)]] + (["Indie"] if i % 3 == 0 else []),
                  "sentiment": rng.choice(["Very Positive", "Mixed", "Mostly Positive"]), "early_access": False})
write("steam_games.json.gz", games)

by_genre = {g: [x for x in games if g in x["genres"]] for g in GENRES}
users = []
for u in range(N_USERS):
    uid = "76561197970982479" if u == 0 else f"fixture_user_{u}"
    taste = rng.sample(GENRES, 2)
    pool = by_genre[taste[0]] * 3 + by_genre[taste[1]] * 2 + games
    lib = {int(rng.choice(pool)["id"]) for _ in range(rng.randint(25, 45))}
    users.append({"user_id": uid, "items_count": len(lib), "steam_id": uid, "user_url": "",
                  "items": [{"item_id": str(g), "item_name": "", "playtime_forever": rng.randint(0, 3000),
                             "playtime_2weeks": 0} for g in lib]})
write("australian_users_items.json.gz", users)

write("australian_user_reviews.json.gz", [
    {"user_id": u["user_id"], "user_url": "", "reviews": [
        {"item_id": it["item_id"], "recommend": rng.random() < 0.8, "posted": "Posted May 1, 2015.",
         "review": "fixture review", "funny": "", "helpful": ""} for it in u["items"][:2]]}
    for u in users[:200]])
print(f"fixture: {N_GAMES} games, {N_USERS} users -> {OUT}")
