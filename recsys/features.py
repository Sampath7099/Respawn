"""Ranker features. Imported by both training (recsys/train.py) and serving
(backend/app/recs.py), so the two cannot drift apart.

Every feature is scale-free with respect to library size: it means the same
thing whether the user's library is the 80% we trained on or the 100% we serve.
"""
import numpy as np

FEATURE_NAMES = ["mf_score", "mf_rank", "log_popularity", "price", "genre_affinity"]


def ranker_features(mf_scores, cands, owned, log_pop, price, genre_codes, n_genres):
    """mf_scores: MF score of each candidate. cands/owned: item indices."""
    owned = np.asarray(list(owned), dtype=int)
    share = np.bincount(genre_codes[owned], minlength=n_genres) / max(len(owned), 1)
    rank = np.argsort(np.argsort(-mf_scores))
    return np.column_stack([mf_scores, rank, log_pop[cands], price[cands], share[genre_codes[cands]]])
