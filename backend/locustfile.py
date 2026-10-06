"""Shopper load: mostly browsing, some game pages, home-page recommendations.

locust -f locustfile.py --headless -u 100 -r 20 -t 60s --host http://127.0.0.1:8010  (not "localhost": on Windows it adds a ~2 s IPv6 fallback per new connection)
"""
import random

from locust import HttpUser, between, task

from app.auth import issue

GENRES = ["Action", "RPG", "Strategy", "Indie", "Simulation", "Adventure", None]
USERS = ["76561197970982479", "js41637", "evcentric", "Riot-Punch", "doctr", "corrupted_soul"]


class Shopper(HttpUser):
    wait_time = between(0.1, 0.5)

    def on_start(self):
        self.h = {"Authorization": "Bearer " + issue(random.choice(USERS))}
        self.ids = [g["game_id"] for g in self.client.get("/games", params={"size": 100}).json()]

    @task(5)
    def browse(self):
        self.client.get("/games", params={"genre": random.choice(GENRES), "page": random.randint(1, 3)},
                        name="/games")

    @task(3)
    def game_page(self):
        self.client.get(f"/games/{random.choice(self.ids)}", name="/games/{id}")

    @task(2)
    def home_recs(self):
        self.client.get("/recommendations", headers=self.h)
