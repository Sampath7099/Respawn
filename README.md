# Respawn

A Steam-style game store with a real data stack behind it: clickstream →
Postgres warehouse (dbt star schema, tested) → SQL analytics, demand
forecasting and A/B testing — orchestrated by Airflow.

**Status:** data platform, storefront API and recommender are done and tested.
Next: the React storefront and switching the A/B test from simulated to model-driven.

## The data

Real data: the [UCSD Steam dataset](https://cseweb.ucsd.edu/~jmcauley/datasets.html#steam_data)
— 32,132 games, 87,626 users, 5,094,082 user–game library rows (with playtime),
59,305 reviews.

Simulated: storefront traffic. There are no real shoppers, so
`simulator/simulate.py` replays 19,354 real Steam users as shoppers for 90 days.
What each user browses comes from the genres they actually play. What they
buy is the games they actually own. Activity decays and users churn, so
retention curves look like a real product. ~585k events. Every user is hashed into an
A/B variant.

> The A/B effect in Phase 1 is injected by the simulator (treatment buys
> slightly more often). It exists to build and validate the analysis. Phase 3
> replaces it with a real recommender vs. a popularity baseline.

## Pipeline

```
data/raw/*.json.gz ──ingest.py──► raw schema (Postgres)
simulator ──────────────────────► raw.events
                 dbt build ──────► staging (views) ──► marts (tables) + 28 tests
Airflow DAG respawn_daily:  ingest_raw → simulate_traffic → source_freshness → dbt_build_and_test
                            (any failed test fails the run and fires the alert callback)
```

Star schema (`marts`): `fct_events`, `fct_orders`, `dim_game`, `dim_user`,
`dim_date`, `agg_daily_kpis`.

Data quality caught a real bug while building this. 1,492 purchases had no
price, for games missing genre metadata. The `not_null` test on
`fct_orders.revenue` failed the build. The fix backfills from the catalogue price.

## Results

**Funnel, retention, segments** (`sql/analytics.sql`, 8 queries: funnels,
cohort retention, top-N per group, running and moving-window GMV, RFM with
NTILE, LAG-based repurchase gaps, wishlist conversion, A/B snapshot)

| Weekly cohort retention | W1 | W2 | W4 |
|---|---|---|---|
| typical cohort | ~50% | ~38% | ~26% |

**A/B readout** (`analysis/ab_test.py`)

| Metric | Control | Treatment | Result |
|---|---|---|---|
| users (SRM check) | 9,743 | 9,611 | p=0.34, split OK |
| buyer rate | 56.35% | 60.63% | +7.6% lift, z=6.04, p=1.5e-9 |
| revenue / user | $14.41 | $16.42 | Welch p=1e-8, bootstrap 95% CI [+$1.32, +$2.70] |

**Demand forecast**: next-day orders per genre, 14-day holdout (`analysis/forecast_demand.py`)

| Model | MAE | WAPE |
|---|---|---|
| naive (same day last week) | 2.78 | 35.5% |
| **7-day moving average** | **1.87** | **23.9%** |
| XGBoost (lags + calendar) | 2.28 | 29.1% |

Honest finding: XGBoost loses. The simulated demand has no weekly seasonality
or trend, so a moving average is close to optimal and the extra model only adds
variance. Always ship the baseline unless the model beats it.

## Storefront API (`backend/`)

FastAPI + Postgres + Redis + Kafka (Redpanda).

- **Catalogue:** search, genre filter and pagination, served through Redis cache-aside.
- **Checkout:** idempotent via an `Idempotency-Key` header and a `UNIQUE(user_id, key)` constraint.
  Eight simultaneous retries of one checkout create exactly one order (tested).
- **Events:** a transactional outbox writes every event in the same transaction
  as the business change. `relay.py publish` ships it to Kafka (`FOR UPDATE SKIP LOCKED`).
  `relay.py consume` sinks it into `raw.events` idempotently (`ON CONFLICT DO NOTHING`)
  and commits offsets only after the rows are durable. That makes delivery at-least-once with no duplicates.
- **Limits and auth:** JWT auth, plus Redis fixed-window rate limits on login and events.
- **Tests:** `pytest` in `backend/tests`, 8 integration tests against real Postgres and Redis.

Load test (Locust, 100 users, 45 s, all on one 8-core laptop, 4 API workers):

| | req/s | p50 | p95 | failures |
|---|---|---|---|---|
| before index on `raw.user_items(user_id)` | 18 | 220 ms | ~39 s (recs) | 0 |
| after index, cache off | 174 | 63 ms | 220 ms | 0 |
| after index, cache on | 204 | 110 ms | 350 ms | 0 |

The index was the real fix: about 9.5x throughput. The cache added 17% throughput, not
lower latency. The load generator, API and Postgres share the same 8 cores, so the
extra requests mostly queued. On separate machines this comparison should be rerun.

## Recommender (`recsys/train.py`)

Two stages, trained on real Steam libraries (60,931 users, 6,079 games, 4.2M
interactions). Training takes about a minute on a laptop CPU.

1. **Candidates:** BPR matrix factorisation in PyTorch (64-d, playtime-weighted), top 100.
2. **Ranking:** XGBoost LambdaMART (`rank:ndcg`) re-ranks the top 100 with popularity, price,
   the user's genre affinity, library size and MF score and rank.

| Model | Recall@10 | NDCG@10 |
|---|---|---|
| popularity | 0.230 | 0.247 |
| BPR-MF | 0.286 | 0.298 |
| **BPR-MF + XGBoost ranker** | **0.304** | **0.317** |

The ranker beats popularity by 28% on NDCG@10. It is evaluated on 5,000 users that
the ranker never trained on. Limitation: Steam libraries have no purchase timestamps,
so the holdout is a random 20% per user, not a time split.

Served at `GET /recommendations`. Control users get popularity and treatment users
get MF + ranker, using the same hash bucketing as the simulator. Brand-new users fall
back to popularity. Results are cached per user for 10 minutes.

## Run it

```bash
docker compose up -d                       # Postgres on :5433
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
python pipeline/ingest.py                  # ~5 min, loads raw data
python simulator/simulate.py               # ~1 min
cd pipeline && dbt build --project-dir dbt --profiles-dir dbt
python analysis/ab_test.py
python analysis/forecast_demand.py

docker compose --profile pipeline up -d    # Airflow UI on :8080 (password in container logs)

python recsys/train.py                     # ~1 min CPU
cd backend && pip install -r requirements.txt
uvicorn app.main:app --port 8010           # API docs at /docs
python -m app.relay publish                # outbox -> Kafka
python -m app.relay consume                # Kafka -> warehouse
pytest -q
```

Download the three files (`steam_games.json.gz`, `australian_users_items.json.gz`,
`australian_user_reviews.json.gz`) into `data/raw/` first.
