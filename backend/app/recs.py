"""Online recommendations from the artifacts written by recsys/train.py.

control   -> popularity (the baseline)
treatment -> BPR-MF top-100 candidates re-ranked by the XGBoost ranker
Unknown / brand-new users get popularity in both arms (cold start).
Features mirror recsys/train.py exactly; keep the two in sync (at serve time the
user's full library is used, at train time the 80% that was not held out).
"""
from pathlib import Path

import numpy as np
import xgboost as xgb

ART = Path(__file__).resolve().parents[2] / "recsys" / "artifacts"


class Recommender:
    def __init__(self):
        m = np.load(ART / "model.npz", allow_pickle=True)
        self.U, self.I, self.B = m["U"], m["I"], m["B"]
        self.item_game = m["item_game"]
        self.game_item = {int(g): i for i, g in enumerate(self.item_game)}
        self.user_row = {u: i for i, u in enumerate(m["user_ids"])}
        self.pop, self.genre, self.price = m["pop"], m["genre_codes"], m["price"]
        self.log_pop = np.log1p(self.pop)
        # plain Booster, not XGBRanker: same model file, no scikit-learn needed to serve
        self.ranker = xgb.Booster()
        self.ranker.load_model(ART / "ranker.json")

    def _mask(self, scores, owned):
        scores = scores.copy()
        scores[owned] = -np.inf
        return scores

    def popular(self, owned, k):
        s = self._mask(self.pop, owned)
        return [int(self.item_game[i]) for i in np.argsort(-s)[:k]]

    def recommend(self, user_id, owned_games, variant, k=10):
        owned = [self.game_item[g] for g in owned_games if g in self.game_item]
        row = self.user_row.get(user_id)
        if variant == "control" or row is None:
            return self.popular(owned, k), "popularity"
        mf = self._mask(self.U[row] @ self.I.T + self.B, owned)
        cands = np.argpartition(-mf, 100)[:100]
        affinity = np.bincount(self.genre[owned], minlength=self.genre.max() + 1) / max(len(owned), 1)
        feats = np.column_stack([mf[cands], np.argsort(np.argsort(-mf[cands])), self.log_pop[cands],
                                 self.price[cands], affinity[self.genre[cands]],
                                 np.full(len(cands), np.log1p(len(owned)))])
        top = cands[np.argsort(-self.ranker.predict(xgb.DMatrix(feats)))[:k]]
        return [int(self.item_game[i]) for i in top], "mf+ranker"

    def similar(self, game_id, k=8):
        """'More like this': nearest games by cosine similarity of MF item embeddings."""
        i = self.game_item.get(game_id)
        if i is None:
            return []
        norm = self.I / (np.linalg.norm(self.I, axis=1, keepdims=True) + 1e-9)
        sims = norm @ norm[i]
        sims[i] = -np.inf
        return [int(self.item_game[j]) for j in np.argsort(-sims)[:k]]
