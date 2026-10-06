# Respawn

A Steam-style game store that learns what you will play next. Behind the
storefront is a complete data platform and an A/B-tested recommender:

```
React storefront ──► FastAPI ──► Postgres (orders, wishlist)      Redis (cache, rate limits)
                        │  transactional outbox
                        ▼
                 Kafka (Redpanda) ──► consumer ──► raw.events
                                                      │
          Airflow: ingest → simulate → freshness → dbt build + 28 tests
                                                      ▼
                                       warehouse (star schema, marts)
                                       ├─► SQL analytics, A/B readout, forecasting
                                       └─► recommender training (PyTorch MF + XGBoost ranker)
                                                      │
                     GET /recommendations ◄───────────┘   control: popularity · treatment: model
```

## The data: real libraries, simulated shopping

**Real data:** the [UCSD Steam dataset](https://cseweb.ucsd.edu/~jmcauley/datasets.html#steam_data).
It has 32,132 games, 87,626 users, 5,094,082 user–game library rows (with playtime)
and 59,305 reviews.

**Simulated:** the storefront traffic. There are no real shoppers, so
`simulator/simulate.py` turns 15,545 real Steam users into shoppers for 90 days:

- About 20% of each shopper's real library is held back as their **future**: the games
  they will buy at Respawn (`recsys/split.py`). The recommender never trains on these.
- Every session shows a "Picked for you" row from the shopper's A/B arm. If the row
  contains a game from their future, they may click it and buy it.
- Shoppers also find future games on their own, at the same rate in both arms. So
  **any difference between arms comes from the model**, not from the simulator.
- Activity decays and users churn, giving real-looking retention (about 50% at week 1,
  26% at week 4).

## Data platform (`pipeline/`, `sql/`, `analysis/`)

- **Ingest:** `pipeline/ingest.py` validates the dataset and loads it into Postgres.
- **Warehouse:** dbt builds a star schema (`fct_events`, `fct_orders`, `dim_game`,
  `dim_user`, `dim_date`, `agg_daily_kpis`) with **28 data tests**.
- **Orchestration:** the Airflow DAG `respawn_daily` runs ingest → simulate → source
  freshness → dbt build. Any failed test fails the run and fires an alert callback.
- **Analytics:** `sql/analytics.sql` has 8 queries: conversion funnel, weekly cohort
  retention, top-N per genre, running and 7-day moving GMV, RFM segments (NTILE),
  repurchase gaps (LAG), wishlist conversion, and an A/B snapshot.

**Bugs the data tests caught:**

1. **Missing prices.** 1,492 purchases had no price (games missing genre metadata).
   The `not_null` test on `fct_orders.revenue` failed the build. The fix backfills
   from the catalogue price.
2. **Broken A/B split.** The first model-driven run put **all 15,545 shoppers in
   control**. The sample-ratio-mismatch check flagged it. Cause: shoppers were picked
   by `md5(user) % 4 == 0`, which forces `md5(user) % 2 == 0`, and unsalted `% 2` was
   also the A/B bucket. The fix salts the experiment hash with the experiment name
   (`backend/app/experiment.py`).

### A/B test: home-page recommendations (`analysis/ab_test.py`)

| Metric | Control (popularity) | Treatment (MF + ranker) | Result |
|---|---|---|---|
| users | 7,777 | 7,768 | SRM p=0.94, split OK |
| rec row CTR per session | 13.14% | 14.87% | +13.2%, p=3.5e-13 * |
| buyer rate | 53.98% | 55.96% | **+3.7%, z=2.48, p=0.013** |
| revenue / user | $10.02 | $11.12 | +11%, Welch p=4e-4, bootstrap 95% CI [+$0.49, +$1.69] |

\* Sessions from the same user are correlated, so this p-value is optimistic.
The per-user buyer-rate test is the decision metric.

### Demand forecast (`analysis/forecast_demand.py`)

The task is next-day orders per genre, scored on a 14-day holdout. XGBoost with lag
and calendar features does **not** beat a 7-day moving average. The simulated demand
has no weekly seasonality, so the baseline is close to optimal. Always ship the
baseline unless the model beats it.

## Recommender (`recsys/`)

Trained on 60,516 real libraries, 6,079 games and 4.0M interactions, with shoppers'
future purchases excluded. Training takes about a minute on a laptop CPU.

1. **Candidates:** BPR matrix factorisation in PyTorch (64-d, playtime-weighted), top 100.
2. **Ranking:** XGBoost LambdaMART (`rank:ndcg`) re-ranks the top 100 with the MF score
   and rank, popularity, price, the user's genre affinity and library size.

| Model | Recall@10 | NDCG@10 |
|---|---|---|
| popularity | 0.220 | 0.235 |
| BPR-MF | 0.270 | 0.275 |
| **BPR-MF + XGBoost ranker** | **0.285** | **0.292** (+24% vs popularity) |

These are scored on 5,000 users that the ranker never trained on. Limitation: Steam
libraries have no purchase timestamps, so the offline holdout is a random 20% per
user, not a time split.

The same item embeddings power "More like this" on game pages (cosine nearest neighbours).

## Storefront

**API (`backend/`)**, built with FastAPI:

- **Caching and limits:** Redis cache-aside for catalogue reads, and fixed-window rate
  limits on login and clickstream.
- **Idempotent checkout:** an `Idempotency-Key` header plus a `UNIQUE(user_id, key)`
  constraint. Eight simultaneous retries of one checkout create exactly one order (tested).
- **Transactional outbox:** each event is written in the same transaction as the business
  change. A relay ships it to Kafka (`FOR UPDATE SKIP LOCKED`). A consumer writes
  `raw.events` idempotently and commits offsets only after the rows are durable, so
  delivery is at-least-once with no duplicates.
- **Recommendations:** `/recommendations` serves the A/B arm. New users fall back to
  popularity. The XGBoost model is served as a plain Booster, so scikit-learn isn't
  needed at runtime.
- **Tests:** 11 integration tests against real Postgres and Redis.

**Frontend (`frontend/`)**, built with React + Vite:

- Pages: store home with the "Picked for you" row, browse/search, game page with
  "More like this", cart, library/wishlist, and a live analytics page (KPIs and the A/B readout).
- Clicks are batched to `/events`. Clicks on the recommendation row are logged as `rec_click`.
- Served by nginx, which proxies `/api` to the API (same origin, no CORS).

**Load test** (Locust, 100 users, one 8-core laptop):

| | req/s | p50 | p95 |
|---|---|---|---|
| before index on `raw.user_items(user_id)` | 18 | 220 ms | ~39 s (recs) |
| after index, cache off | 174 | 63 ms | 220 ms |
| after index, cache on | 204 | 110 ms | 350 ms |

The index was the real fix: about 9.5x the throughput. The cache added 17% more
throughput but not lower latency. The load generator, API and Postgres all share the
same 8 cores, so the extra requests mostly queued.

## Run it

Put `steam_games.json.gz`, `australian_users_items.json.gz` and
`australian_user_reviews.json.gz` (from the dataset page) in `data/raw/`. Then:

```bash
docker compose up -d postgres redis redpanda
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt torch
python pipeline/ingest.py                  # ~5 min
cd pipeline && dbt build --project-dir dbt --profiles-dir dbt && cd ..   # dim_game for training
python recsys/train.py                     # ~1 min, CPU
python simulator/simulate.py               # ~40 s, uses the trained model
cd pipeline && dbt build --project-dir dbt --profiles-dir dbt && cd ..
python analysis/ab_test.py

docker compose up -d --build               # API :8010, storefront http://localhost:3000
docker compose --profile pipeline up -d    # Airflow :8080 (daily DAG)

cd backend && pip install -r requirements.txt && pytest -q
```

Retraining is a separate step from the daily DAG. The simulator and the API read
the artifacts in `recsys/artifacts/`.
