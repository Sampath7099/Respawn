"""Two-stage game recommender, trained on real Steam libraries.

Stage 1 (candidates): BPR matrix factorisation in PyTorch on "user owns game",
                      weighted by log playtime. Top-100 per user.
Stage 2 (ranking):    XGBoost LambdaMART re-ranks the 100 (features: recsys/features.py).

Protocol
- Shoppers' future purchases (recsys/split.py) are removed before anything else.
- 20% of each remaining user's library is held out (random: Steam has no timestamps).
- Eval users are shuffled and split in two. "fit" users choose the MF epoch count
  and train the ranker; "hold" users are only used for the final numbers.
- Metrics are standard Recall@K (hits / |held-out|) and NDCG@K, averaged over users,
  with a 95% bootstrap CI over users, repeated for several seeds.
- The shipped model is refit on ALL interactions with the chosen epoch count.
  The ranker is reused: its features are scale-free (see features.py).
"""
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
import torch
from xgboost import XGBRanker

from features import FEATURE_NAMES, ranker_features
from split import is_future

DSN = os.environ.get("RESPAWN_DSN", "postgresql://respawn:respawn@localhost:5433/respawn")
OUT = Path(os.environ.get("RESPAWN_ARTIFACTS", Path(__file__).parent / "artifacts"))
OUT.mkdir(exist_ok=True)
K, DIM, MAX_EPOCHS = 10, 64, int(os.environ.get("MAX_EPOCHS", 8))
SEEDS = [int(s) for s in os.environ.get("SEEDS", "0,1,2").split(",")]
MIN_OWNERS = int(os.environ.get("MIN_OWNERS", 20))
split_rng = np.random.default_rng(0)  # the data split is fixed; seeds vary the models

# ---------------------------------------------------------------- data
with psycopg.connect(DSN) as conn:
    inter = pd.read_sql("""
        SELECT i.user_id, i.game_id, i.playtime_forever
        FROM raw.user_items i JOIN marts.dim_game g USING (game_id)
        WHERE g.owners >= %(m)s""", conn, params={"m": MIN_OWNERS})
    games = pd.read_sql("SELECT game_id, price, primary_genre FROM marts.dim_game WHERE owners >= %(m)s",
                        conn, params={"m": MIN_OWNERS})

future = np.fromiter((is_future(u, g) for u, g in zip(inter.user_id, inter.game_id, strict=True)), bool, len(inter))
inter = inter[~future]
inter = inter[inter.groupby("user_id").game_id.transform("size") >= 5].copy()
uids, gids = inter.user_id.astype("category"), inter.game_id.astype("category")
inter["u"], inter["i"] = uids.cat.codes.values, gids.cat.codes.values
n_users, n_items = inter.u.max() + 1, inter.i.max() + 1
N_CAND = min(100, n_items - 1)
item_game = np.asarray(gids.cat.categories)
games = games.set_index("game_id").loc[item_game].reset_index()
genre_codes = games.primary_genre.astype("category").cat.codes.values
n_genres = genre_codes.max() + 1
price = games.price.fillna(0).values.astype(float)
print(f"excluded {future.sum()} future purchases | users={n_users} games={n_items} interactions={len(inter)}")

inter["test"] = split_rng.random(len(inter)) < 0.2
train, test = inter[~inter.test], inter[inter.test]
train_sets = train.groupby("u").i.apply(set).to_dict()
eval_users = split_rng.permutation(test.u.unique())[:10000]
test_sets = test[test.u.isin(eval_users)].groupby("u").i.apply(set).to_dict()
users = [u for u in eval_users if u in test_sets]
fit_users, hold_users = users[:len(users) // 2], users[len(users) // 2:]
pop = np.bincount(train.i.values, minlength=n_items).astype(float)  # train only
log_pop = np.log1p(pop)


# ---------------------------------------------------------------- helpers
def topn(scores, seen, n):
    scores = scores.copy()
    scores[list(seen)] = -np.inf
    top = np.argpartition(-scores, n)[:n]
    return top[np.argsort(-scores[top])]


def per_user_metrics(recs, us):
    """Standard Recall@K = hits/|truth|; NDCG@K with the ideal DCG of min(|truth|, K) hits."""
    disc = 1 / np.log2(np.arange(2, K + 2))
    rec, ndcg = [], []
    for u in us:
        truth = test_sets[u]
        hits = np.array([i in truth for i in recs[u][:K]], dtype=float)
        rec.append(hits.sum() / len(truth))
        ndcg.append((hits * disc).sum() / disc[:min(len(truth), K)].sum())
    return np.array(rec), np.array(ndcg)


def bootstrap_ci(x, n=1000, seed=0):
    r = np.random.default_rng(seed)
    means = [x[r.integers(0, len(x), len(x))].mean() for _ in range(n)]
    return np.percentile(means, [2.5, 97.5])


def train_mf(df, seed, epochs, select_on=None):
    """BPR-MF. With select_on (a list of users), keeps the epoch with the best Recall@K on them."""
    torch.manual_seed(seed)
    U = torch.nn.Embedding(n_users, DIM)
    I = torch.nn.Embedding(n_items, DIM)
    B = torch.nn.Embedding(n_items, 1)
    for e in (U, I):
        torch.nn.init.normal_(e.weight, std=0.05)
    torch.nn.init.zeros_(B.weight)
    params = list(U.parameters()) + list(I.parameters()) + list(B.parameters())
    opt = torch.optim.Adam(params, lr=5e-3)
    u_t = torch.tensor(df.u.values, dtype=torch.long)
    i_t = torch.tensor(df.i.values, dtype=torch.long)
    w_t = torch.tensor(np.log1p(df.playtime_forever.values / 60) + 1, dtype=torch.float32)  # played more = stronger
    seen = df.groupby("u").i.apply(set).to_dict()
    best, best_score, history = None, -1.0, []
    for epoch in range(epochs):
        perm = torch.randperm(len(u_t))
        for s in range(0, len(perm), 16384):
            idx = perm[s:s + 16384]
            u, pos, w = u_t[idx], i_t[idx], w_t[idx]
            neg = torch.randint(0, n_items, (len(idx),))
            pos_s = (U(u) * I(pos)).sum(-1) + B(pos).squeeze(-1)
            neg_s = (U(u) * I(neg)).sum(-1) + B(neg).squeeze(-1)
            loss = -(w * torch.nn.functional.logsigmoid(pos_s - neg_s)).mean()
            loss = loss + 1e-5 * (U(u).pow(2).sum() + I(pos).pow(2).sum()) / len(idx)
            opt.zero_grad()
            loss.backward()
            opt.step()
        mats = tuple(m.weight.detach().numpy().copy() for m in (U, I, B))
        if select_on is None:
            best = mats
            continue
        recs = {u: topn(mats[0][u] @ mats[1].T + mats[2].ravel(), seen.get(u, set()), K) for u in select_on}
        score_ = per_user_metrics(recs, select_on)[0].mean()
        history.append(round(float(score_), 4))
        if score_ > best_score:
            best, best_score, best_epoch = mats, score_, epoch + 1
    if select_on is None:
        return best[0], best[1], best[2].ravel(), epochs, []
    return best[0], best[1], best[2].ravel(), best_epoch, history


def feats(u, cands, U, I, B, owned):
    return ranker_features(U[u] @ I[cands].T + B[cands], cands, owned, log_pop, price, genre_codes, n_genres)


# ---------------------------------------------------------------- evaluation over seeds
results = {"popularity": [], "BPR-MF": [], "BPR-MF + XGBoost ranker": []}
pop_recs = {u: topn(pop, train_sets.get(u, set()), K) for u in hold_users}
first = None
for seed in SEEDS:
    t0 = time.time()
    U, I, B, epochs, hist = train_mf(train, seed, MAX_EPOCHS, select_on=fit_users)
    cands = {u: topn(U[u] @ I.T + B, train_sets.get(u, set()), N_CAND) for u in users}
    X = [feats(u, cands[u], U, I, B, train_sets.get(u, set())) for u in fit_users]
    y = [[int(i in test_sets[u]) for i in cands[u]] for u in fit_users]
    ranker = XGBRanker(objective="rank:ndcg", n_estimators=200, max_depth=6, learning_rate=0.1,
                       eval_metric=f"ndcg@{K}", random_state=seed)
    ranker.fit(np.vstack(X), np.concatenate(y), group=[len(c) for c in y])
    ranked = {u: cands[u][np.argsort(-ranker.predict(feats(u, cands[u], U, I, B, train_sets.get(u, set()))))]
              for u in hold_users}
    for name, recs in [("popularity", pop_recs), ("BPR-MF", cands), ("BPR-MF + XGBoost ranker", ranked)]:
        results[name].append(per_user_metrics(recs, hold_users))
    print(f"seed {seed}: best epoch {epochs} (fit-user recall by epoch {hist}) [{time.time() - t0:.0f}s]")
    if first is None:
        first = (ranker, epochs)

summary = {}
print(f"\n{len(hold_users)} held-out users, {len(SEEDS)} seeds. mean over seeds; 95% bootstrap CI over users (seed {SEEDS[0]})")
for name, runs in results.items():
    rec = [r.mean() for r, _ in runs]
    ndcg = [n.mean() for _, n in runs]
    lo, hi = bootstrap_ci(runs[0][1])
    summary[name] = {"recall": float(np.mean(rec)), "recall_sd": float(np.std(rec)),
                     "ndcg": float(np.mean(ndcg)), "ndcg_sd": float(np.std(ndcg)), "ndcg_ci": [float(lo), float(hi)]}
    print(f"  {name:<26} Recall@{K}={np.mean(rec):.4f}±{np.std(rec):.4f}  "
          f"NDCG@{K}={np.mean(ndcg):.4f}±{np.std(ndcg):.4f}  CI=[{lo:.4f}, {hi:.4f}]")

# ---------------------------------------------------------------- ship: refit MF on everything
ranker, epochs = first
U, I, B, _, _ = train_mf(inter, SEEDS[0], epochs)
pop_all = np.bincount(inter.i.values, minlength=n_items).astype(float)
np.savez_compressed(OUT / "model.npz", U=U, I=I, B=B, item_game=item_game,
                    user_ids=np.asarray(uids.cat.categories), pop=pop_all,
                    # ranker feature uses the same train-split popularity it was fit on
                    log_pop_feature=log_pop, genre_codes=genre_codes, price=price)
ranker.save_model(OUT / "ranker.json")
(OUT / "metrics.json").write_text(json.dumps({"k": K, "features": FEATURE_NAMES, "epochs": epochs,
                                              "seeds": SEEDS, "hold_users": len(hold_users),
                                              "results": summary}, indent=2))
print(f"refit on all {len(inter)} interactions ({epochs} epochs); saved artifacts -> {OUT}")
