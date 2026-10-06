"""Two-stage game recommender, trained on real Steam libraries.

Stage 1 (candidates): matrix factorisation in PyTorch with BPR loss on
          "user owns game" (weighted by log playtime). Top-100 per user.
Stage 2 (ranking):    XGBoost LambdaMART re-ranks those 100 with features the
          MF model can't see: popularity, price, genre affinity, library size.

Evaluation: for each user, 20% of their library is held out. Steam libraries
carry no purchase timestamps, so this is a random per-user holdout, not a
time split; stated as a limitation. Metrics on held-out users' hidden games:
Recall@10 and NDCG@10, against a popularity baseline.
"""
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
import torch
from xgboost import XGBRanker

DSN = os.environ.get("RESPAWN_DSN", "postgresql://respawn:respawn@localhost:5433/respawn")
OUT = Path(__file__).parent / "artifacts"
OUT.mkdir(exist_ok=True)
K, N_CAND, DIM = 10, 100, 64
rng = np.random.default_rng(0)
torch.manual_seed(0)

# ---------------------------------------------------------------- data
with psycopg.connect(DSN) as conn:
    inter = pd.read_sql("""
        SELECT i.user_id, i.game_id, i.playtime_forever
        FROM raw.user_items i
        JOIN marts.dim_game g USING (game_id)
        WHERE g.owners >= 20""", conn)
    games = pd.read_sql("SELECT game_id, price, primary_genre, owners FROM marts.dim_game WHERE owners >= 20", conn)

lib_size = inter.groupby("user_id").game_id.transform("size")
inter = inter[lib_size >= 5].copy()
uids, gids = inter.user_id.astype("category"), inter.game_id.astype("category")
inter["u"], inter["i"] = uids.cat.codes.values, gids.cat.codes.values
n_users, n_items = inter.u.max() + 1, inter.i.max() + 1
item_game = np.asarray(gids.cat.categories)
games = games.set_index("game_id").loc[item_game].reset_index()
print(f"users={n_users} games={n_items} interactions={len(inter)}")

# per-user 20% holdout
inter["test"] = rng.random(len(inter)) < 0.2
train, test = inter[~inter.test], inter[inter.test]
eval_users = rng.choice(test.u.unique(), size=min(10000, test.u.nunique()), replace=False)
test_sets = test[test.u.isin(eval_users)].groupby("u").i.apply(set).to_dict()
train_sets = train.groupby("u").i.apply(set).to_dict()

# ---------------------------------------------------------------- stage 1: BPR-MF
class MF(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.U = torch.nn.Embedding(n_users, DIM)
        self.I = torch.nn.Embedding(n_items, DIM)
        self.b = torch.nn.Embedding(n_items, 1)
        for e in (self.U, self.I):
            torch.nn.init.normal_(e.weight, std=0.05)
        torch.nn.init.zeros_(self.b.weight)

    def score(self, u, i):
        return (self.U(u) * self.I(i)).sum(-1) + self.b(i).squeeze(-1)


model = MF()
opt = torch.optim.Adam(model.parameters(), lr=5e-3)
u_t = torch.tensor(train.u.values, dtype=torch.long)
i_t = torch.tensor(train.i.values, dtype=torch.long)
w_t = torch.tensor(np.log1p(train.playtime_forever.values / 60) + 1, dtype=torch.float32)  # played more = stronger signal
t0 = time.time()
for epoch in range(6):
    perm = torch.randperm(len(u_t))
    total = 0.0
    for s in range(0, len(perm), 16384):
        idx = perm[s:s + 16384]
        u, pos, w = u_t[idx], i_t[idx], w_t[idx]
        neg = torch.randint(0, n_items, (len(idx),))
        loss = -(w * torch.nn.functional.logsigmoid(model.score(u, pos) - model.score(u, neg))).mean()
        loss = loss + 1e-5 * (model.U(u).pow(2).sum() + model.I(pos).pow(2).sum()) / len(idx)
        opt.zero_grad()
        loss.backward()
        opt.step()
        total += loss.item() * len(idx)
    print(f"epoch {epoch} bpr_loss={total / len(perm):.4f}  ({time.time() - t0:.0f}s)")

with torch.no_grad():
    U = model.U.weight.numpy()
    I = model.I.weight.numpy()
    B = model.b.weight.numpy().ravel()


def topn(scores, seen, n):
    scores = scores.copy()
    scores[list(seen)] = -np.inf
    top = np.argpartition(-scores, n)[:n]
    return top[np.argsort(-scores[top])]


def metrics(recs):
    rec, ndcg = [], []
    disc = 1 / np.log2(np.arange(2, K + 2))
    for u, items in recs.items():
        truth = test_sets[u]
        hits = np.array([i in truth for i in items[:K]], dtype=float)
        rec.append(hits.sum() / min(len(truth), K))
        ndcg.append((hits * disc).sum() / disc[:min(len(truth), K)].sum())
    return np.mean(rec), np.mean(ndcg)


pop = np.bincount(train.i.values, minlength=n_items).astype(float)
users = list(test_sets)
pop_recs = {u: topn(pop, train_sets.get(u, set()), K) for u in users}
mf_cands = {u: topn(U[u] @ I.T + B, train_sets.get(u, set()), N_CAND) for u in users}

# ---------------------------------------------------------------- stage 2: XGBoost LambdaMART
genre_codes = games.primary_genre.astype("category").cat.codes.values
n_genres = genre_codes.max() + 1
price = games.price.fillna(0).values.astype(float)
log_pop = np.log1p(pop)


def features(u, cands):
    owned = list(train_sets.get(u, set()))
    affinity = np.bincount(genre_codes[owned], minlength=n_genres) / max(len(owned), 1)
    mf = U[u] @ I[cands].T + B[cands]
    return np.column_stack([mf, np.argsort(np.argsort(-mf)), log_pop[cands], price[cands],
                            affinity[genre_codes[cands]], np.full(len(cands), np.log1p(len(owned)))])


# train the ranker on half the eval users, evaluate on the other half (no overlap)
half = len(users) // 2
fit_users, hold_users = users[:half], users[half:]
X, y, groups = [], [], []
for u in fit_users:
    c = mf_cands[u]
    X.append(features(u, c))
    y.append([int(i in test_sets[u]) for i in c])
    groups.append(len(c))
ranker = XGBRanker(objective="rank:ndcg", n_estimators=200, max_depth=6, learning_rate=0.1,
                   eval_metric="ndcg@10", random_state=0)
ranker.fit(np.vstack(X), np.concatenate(y), group=groups)

ranked = {u: mf_cands[u][np.argsort(-ranker.predict(features(u, mf_cands[u])))] for u in hold_users}

print(f"\nEvaluated on {len(hold_users)} held-out users (Recall@{K}, NDCG@{K}):")
for name, recs in [("popularity", pop_recs), ("BPR-MF", mf_cands), ("BPR-MF + XGBoost ranker", ranked)]:
    r, n = metrics({u: recs[u] for u in hold_users})
    print(f"  {name:<26} recall={r:.4f}  ndcg={n:.4f}")
cov = len({i for u in hold_users for i in ranked[u][:K]}) / n_items
print(f"  catalogue coverage of ranker top-{K}: {cov:.1%}")

np.savez_compressed(OUT / "model.npz", U=U, I=I, B=B, item_game=item_game,
                    user_ids=np.asarray(uids.cat.categories), pop=pop,
                    genre_codes=genre_codes, price=price)
ranker.save_model(OUT / "ranker.json")
print("saved artifacts ->", OUT)
