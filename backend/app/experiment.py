"""A/B assignment, shared by the API and the simulator so buckets always match.

The hash is salted with the experiment name. Unsalted md5(user_id) % 2 is
perfectly correlated with any other md5(user_id) rule. Shopper selection uses
% 4 == 0, which put every shopper in control. The SRM check caught it.
"""
import hashlib

EXPERIMENT = "home-recs-v1"


def variant(user_id):
    h = int(hashlib.md5(f"{EXPERIMENT}:{user_id}".encode()).hexdigest(), 16)
    return "treatment" if h % 2 else "control"
