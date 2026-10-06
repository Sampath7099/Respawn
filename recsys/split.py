"""Which users shop in the simulated store, and which of their games are "future" purchases.

Shared by recsys/train.py and simulator/simulate.py so the model is never
trained on a game a simulated shopper has not bought yet. Without this, the
A/B test would measure memorisation, not recommendation quality.
"""
import hashlib


def _h(s):
    return int(hashlib.md5(s.encode()).hexdigest(), 16)


def is_store_user(user_id):
    """~25% of Steam users act as Respawn shoppers."""
    return _h(user_id) % 4 == 0


def is_future(user_id, game_id):
    """~20% of a shopper's real library is bought during the simulation, the rest is history."""
    return is_store_user(user_id) and _h(f"{user_id}:{game_id}") % 5 == 0
