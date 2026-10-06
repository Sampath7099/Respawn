"""Online recommendations from the artifacts written by recsys/train.py.

control   -> popularity
treatment -> BPR-MF top-100 candidates re-ranked by the XGBoost ranker
Users the model has never seen get popularity in both arms (cold start).
Ranker features come from recsys/features.py, the same code training uses.
"""
import os
import sys
from pathlib import Path

import numpy as np
import xgboost as xgb

RECSYS = Path(__file__).resolve().parents[2] / "recsys"
sys.path.insert(0, str(RECSYS))
from features import ranker_features  # noqa: E402

ART = Path(os.environ.get("RESPAWN_ARTIFACTS", RECSYS / "artifacts"))


class Recommender:
    def __init__(self):
        m = np.load(ART / "model.npz", allow_pickle=True)
        self.U, self.I, self.B = m["U"], m["I"], m["B"]
        self.I_norm = self.I / (np.linalg.norm(self.I, axis=1, keepdims=True) + 1e-9)
        self.item_game = m["item_game"]
        self.game_item = {int(g): i for i, g in enumerate(self.item_game)}
        self.user_row = {u: i for i, u in enumerate(m["user_ids"])}
        self.pop, self.log_pop_feature = m["pop"], m["log_pop_feature"]
        self.genre, self.price = m["genre_codes"], m["price"]
        self.n_genres = self.genre.max() + 1
        self.n_cand = min(100, len(self.item_game) - 1)
        self.ranker = xgb.Booster()  # plain Booster: same model file, no scikit-learn at serve time
        self.ranker.load_model(ART / "ranker.json")

    def popular(self, owned, k):
        s = self.pop.copy()
        s[owned] = -np.inf
        return [int(self.item_game[i]) for i in np.argsort(-s)[:k]]

    def recommend(self, user_id, owned_games, variant, k=10):
        owned = [self.game_item[g] for g in owned_games if g in self.game_item]
        row = self.user_row.get(user_id)
        if variant == "control" or row is None:
            return self.popular(owned, k), "popularity"
        mf = self.U[row] @ self.I.T + self.B
        mf[owned] = -np.inf
        cands = np.argpartition(-mf, self.n_cand)[:self.n_cand]
        X = ranker_features(mf[cands], cands, owned, self.log_pop_feature, self.price, self.genre, self.n_genres)
        top = cands[np.argsort(-self.ranker.predict(xgb.DMatrix(X)))[:k]]
        return [int(self.item_game[i]) for i in top], "mf+ranker"

    def similar(self, game_id, k=8):
        """'More like this': nearest games by cosine similarity of item embeddings."""
        i = self.game_item.get(game_id)
        if i is None:
            return []
        sims = self.I_norm @ self.I_norm[i]
        sims[i] = -np.inf
        return [int(self.item_game[j]) for j in np.argsort(-sims)[:k]]
