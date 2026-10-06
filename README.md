# Respawn

A Steam-style game store with a recommender, an A/B test, and the data platform
behind them. Every number below comes from a file in [`results/`](results/).

```
React ──► nginx ──► FastAPI ──► Postgres (orders, wishlist, outbox)     Redis (cache, rate limits, trending)
                        │ transactional outbox
                        ▼
              relay ──► Kafka "events" ──┬──► sink-warehouse ──► raw.events ─┐
                                         └──► sink-trending ──► Redis       │
                                                                             ▼
   Airflow respawn_daily: freshness ─► dbt build (models + tests) ─► marts (star schema)
                                                                             │
           recsys/train.py (offline) ◄──────────────────────────────────────┤
                     │                                       analysis/ (A/B, forecast), sql/
                     ▼
          GET /recommendations   control: popularity · treatment: BPR-MF + XGBoost ranker
```

## Data: real libraries, simulated shopping

**Real data:** the [UCSD Steam dataset](https://cseweb.ucsd.edu/~jmcauley/datasets.html#steam_data).
It has 32,132 games, 87,626 users, 5,094,082 user–game library rows with playtime,
and 59,305 reviews.

**Simulated:** there are no real shoppers, so `simulator/simulate.py` turns 15,501 real
Steam users into shoppers for 90 days. The parameters at the top of that file are
assumptions, not measurements:

- **Purchases come from the real library.** About 20% of each shopper's library is
  their "future": games they will buy (`recsys/split.py`). The model never trains on it.
- **The recommendation row.** Every session shows a 10-game row from the shopper's arm.
  Slot *i* is looked at with probability 0.6 / log2(*i*+2).
- **Clicks and purchases.** A looked-at game is clicked at 45% if the shopper wants it
  and 3% otherwise. Wanted games are often bought; others are rarely impulse-bought.
  Unbought wanted games may be wishlisted.
- **Row refresh.** The row is recomputed after every purchase.
- **Organic discovery.** Shoppers also find wanted games without recommendations, at
  the same rate in both arms.
- **Seasonality and churn.** Purchase intent is 1.5x at weekends. Activity decays and
  users churn, which produces the retention curves (about 50% at week 1, 26% at week 4).
  Those curves are a consequence of the parameters, not a finding.

The live storefront writes to `raw.events` and the simulator writes to `raw.sim_events`.
dbt unions them, and nothing ever truncates live data.

## Data platform

- **Ingest:** `pipeline/ingest.py` parses the dataset (Python-literal lines, not JSON)
  and loads it. Prices that can't be parsed are stored as NULL and mean **not for sale**.
  They are never silently priced at $0.
- **dbt star schema:** `fct_events`, `fct_order_items` (grain: one game in an order),
  `fct_orders` (grain: one order), `dim_game` (including review stats), `dim_user`,
  `dim_date` and `agg_daily_kpis`. Live orders come from the store's own tables; each
  simulated purchase is a one-item order. There are 37 models and tests, including:
  - `assert_one_variant_per_user`: a user in both arms means assignment is broken.
  - `assert_orders_match_order_items`: every line item is counted exactly once.
  - `not_null(revenue)`: it can fail, because there is no fallback to 0 anymore.
- **Airflow:** `respawn_daily` runs a live-traffic freshness check (warns after 24 h
  without events) and then `dbt build`. `respawn_bootstrap` is run manually: it loads the
  dataset (skipped if already loaded), simulates history, and builds. Training is a
  separate offline step because it needs torch.
- **SQL:** `sql/analytics.sql` has 7 questions: funnel, weekly cohort retention, top-3
  per genre, running and 7-day GMV, RFM on orders, repurchase gaps, and wishlist
  conversion by price band.

## Recommender ([`results/recsys_metrics.json`](results/recsys_metrics.json))

Trained on 60,516 libraries, 6,079 games and 4.0M interactions, with shoppers' future
purchases removed.

1. **Candidates:** BPR matrix factorisation in PyTorch (64-d, weighted by log
   playtime), top 100.
2. **Ranking:** XGBoost LambdaMART (`rank:ndcg`) over 5 features in
   `recsys/features.py`. The same module is imported by training and by the API, and
   every feature is independent of library size.

**Protocol:**
- 20% of each user's library is held out at random. Steam has no purchase timestamps,
  so a time split isn't possible; this is a limitation.
- Evaluation users are shuffled and split in two. The "fit" half chooses the MF epoch
  count (validation recall peaked at 14 of 15) and trains the ranker. The "hold" half
  (5,000 users) is used only for the numbers below.
- Metrics are standard Recall@10 (hits / |held out|) and NDCG@10, averaged over 3 seeds.
  The 95% bootstrap CI is computed over users.
- The shipped model is refit on all interactions.

| Model | Recall@10 | NDCG@10 | NDCG@10 95% CI |
|---|---|---|---|
| popularity | 0.170 | 0.218 | [0.213, 0.224] |
| BPR-MF | 0.208 ± 0.000 | 0.264 ± 0.000 | [0.258, 0.270] |
| **BPR-MF + XGBoost ranker** | **0.226 ± 0.001** | **0.292 ± 0.001** | [0.284, 0.297] |

The same item embeddings power "More like this" (cosine nearest neighbours).

## A/B test: home-recs-v1 ([`results/ab_test.txt`](results/ab_test.txt))

The plan was fixed in `analysis/ab_test.py` before reading any result:
- Users are randomised and analysed.
- **Guardrail:** sample-ratio check.
- **Primary metric:** buyer rate.
- **Secondary metrics:** revenue per user and recommendation-row CTR per user,
  Holm-corrected.

| | Control (popularity) | Treatment (model) | |
|---|---|---|---|
| users (SRM) | 7,751 | 7,750 | p = 0.99 |
| **buyer rate (primary)** | 58.47% | 63.05% | **+7.8%, z = 5.83, p = 5e-9** |
| revenue / user | $12.56 | $15.91 | +27%, Holm p = 2e-19, 95% CI of difference [$2.65, $4.07] |
| rec-row CTR / user | 21.5% | 26.8% | +25%, Holm p = 2e-29 |

**What this shows and what it doesn't.** The arms differ only in the rows they show,
so this tests the whole loop: assignment → serving → events → warehouse → analysis. It
also shows how a better offline ranking turns into conversions under a position-biased
click model. It is **not** evidence of real-world lift, because the effect size depends
on the simulator's assumed click and purchase rates.

The assignment hash is salted with the experiment name (`backend/app/experiment.py`).
An unsalted version put every shopper in control: shopper selection used
`md5 % 4 == 0`, which implies `md5 % 2 == 0`. The SRM check caught it, and
`test_variant_is_independent_of_shopper_selection` now guards it.

## Demand forecast ([`results/forecast.txt`](results/forecast.txt))

This forecasts next-day units sold per genre over a 14-day holdout of the simulated history.

| Model | MAE | WAPE |
|---|---|---|
| same day last week | 3.04 | 39.7% |
| 7-day moving average | 2.22 | 29.0% |
| XGBoost, raw orders as target | 3.03 | 39.6% |
| **XGBoost, orders ÷ 7-day mean as target** | **2.11** | **27.6%** |

Demand rises and then decays over the 90 days. Trees can't extrapolate, so the raw-target
model keeps predicting training-period levels. Predicting the ratio to the recent mean
leaves the model only the weekly shape to learn. It's a small win over a strong baseline.

## Storefront

**API (`backend/app/`)**, built with FastAPI:

- **Auth:** demo login with any dataset user id and no password; the accounts are
  public dataset users. The JWT is in an HttpOnly, SameSite=Strict cookie. In
  production, `JWT_SECRET` is required (compose refuses to start without it).
- **Checkout:**
  - An `Idempotency-Key` is stored with a hash of the cart. A replay returns the
    original order, and the same key with a different cart gets 422.
  - Games you already own get 409, and games not for sale get 400.
  - Eight concurrent retries create exactly one order (tested).
- **Recommendations:** the per-user cache is dropped on checkout, so a bought game
  leaves the row immediately. The model loads at boot.
- **Outbox → Kafka:**
  - A row is marked published only after Kafka confirms *that row*.
  - Consumers commit offsets only after a batch is durable.
  - Unparseable or invalid messages go to `events.dlq` with the reason.
  - Event ids come from outbox ids, so redelivery collapses (`ON CONFLICT DO NOTHING`).
- **Why Kafka rather than a direct INSERT:** two independent readers consume the same
  stream. `sink-warehouse` writes `raw.events`, and `sink-trending` keeps hourly
  "trending now" counters in Redis by event time. They lag, fail and replay separately.
- **Rate limits and input checks:**
  - Behind nginx, uvicorn uses `--proxy-headers`, so login limits apply per real
    client IP, not per proxy.
  - Clickstream limits count events, with at most 100 per batch.
  - Query parameters are validated: bad input gets 422, never 500.
- **Session ids** come from the browser tab (`X-Session-Id`), not from when the
  consumer happened to run.

**Frontend (`frontend/`)**, React + Vite:
- Pages: store with "Picked for you" and live trending, browse, game page with
  "More like this", cart, library and wishlist, and analytics (KPIs and the A/B readout).
- Clicks are batched, and the last batch is sent with `keepalive` on page hide.
- The idempotency key changes whenever the cart changes.

**Load test** ([`results/`](results/)): Locust with 100 users for 45 s, all on one
8-core laptop, 4 API workers, all requests passing through Redis-backed rate limiting.

| | req/s | p50 | p95 | API CPU | Postgres CPU | Redis hit rate |
|---|---|---|---|---|---|---|
| cache off | 289 | 10 ms | 45 ms | 131% | 65% | – |
| cache on | 298 | 7 ms | 23 ms | 75% | 24% | 99% |

- **Throughput is capped by Locust's think time,** so it barely moves. The cache's
  effect is on latency and load: p95 halves, and database CPU drops by about 60%.
- **Two earlier bottlenecks were found this way:** a missing index on
  `raw.user_items(user_id)` (18 → 174 req/s), and the model lazily loading in each
  worker on its first request (p95 1.2–5.7 s on recommendations).
- **The `/games?size=100` row in the CSVs** is Locust's per-user setup call. Its ~2 s is
  the Windows `localhost` IPv6 fallback on new connections, not the server: 2.4 s via
  `localhost` vs 0.26 s via `127.0.0.1`.

## Tests and CI

- **Unit tests** (`backend/tests/test_unit.py`, 12): A/B assignment balance and
  independence, the future split, z-test and Holm, scale-free features, cart hashing,
  event validation and dead-lettering, trending buckets, and the relay marking only
  delivered rows (with a fake producer).
- **Integration tests** (`backend/tests/test_api.py`, 22): auth cookie, validation,
  idempotency (replay, mismatch, concurrency), owned and not-for-sale games, the
  clickstream, A/B serving, and cache invalidation. They refuse to run against the
  main database.
- **CI** (`.github/workflows/ci.yml`) runs the **whole pipeline** on a small synthetic
  dataset (`scripts/make_fixture.py`): ingest → dbt build → train → simulate → dbt build
  → A/B readout → all tests. It also runs lint, unit tests, the frontend build and the
  image builds.

## Run it

```bash
cp .env.example .env                      # then set JWT_SECRET
docker compose up -d postgres redis redpanda
python -m venv .venv && .venv/Scripts/pip install torch -r requirements.txt
python pipeline/ingest.py                 # files from the dataset page in data/raw/, ~5 min
dbt build --project-dir pipeline/dbt --profiles-dir pipeline/dbt
python recsys/train.py                    # ~10 min CPU (3 seeds)
python simulator/simulate.py
dbt build --project-dir pipeline/dbt --profiles-dir pipeline/dbt
python analysis/ab_test.py && python analysis/forecast_demand.py

docker compose up -d --build              # storefront http://localhost:3000
docker compose --profile pipeline up -d   # Airflow :8080
```

To run the tests the way CI does, use a separate database (`PGDATABASE` and
`RESPAWN_DSN`) loaded from `python scripts/make_fixture.py`.

## Known limitations

- **No purchase timestamps** in Steam libraries, so the offline evaluation uses a
  random holdout, not a time split.
- **The A/B effect size depends on simulator assumptions.** The pipeline is real; the
  shoppers are not.
- **Demo auth has no passwords** by design (the accounts are public dataset users).
- **The ranker is trained on 80%-library MF scores but serves the refit model.** Its
  features are scale-free and it leans on MF rank, but the score scale can still shift
  slightly.
- **Everything runs on one machine.** The load-test numbers come from a single laptop.
