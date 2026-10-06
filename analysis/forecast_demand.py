"""Forecast next-day units sold per genre with XGBoost; compare against naive baselines.

The simulator gives demand a weekly cycle (higher purchase intent at weekends), so a
model that uses day-of-week has something real to learn. Whether it beats the baselines
is the result, reported either way.

Features are calendar + lagged demand only (no leakage): lag 1/7, 7-day mean.
Backtest: train on all days before the last 14, predict the last 14 days.
"""
import os

import numpy as np
import pandas as pd
import psycopg
from xgboost import XGBRegressor

DSN = os.environ.get("RESPAWN_DSN", "postgresql://respawn:respawn@localhost:5433/respawn")
HOLDOUT_DAYS = 14

with psycopg.connect(DSN) as conn:
    df = pd.read_sql("""
        SELECT oi.order_date AS day, g.primary_genre AS genre, count(*) AS orders
        FROM marts.fct_order_items oi JOIN marts.dim_game g USING (game_id)
        WHERE oi.order_id LIKE 'sim-%%'  -- the 90-day simulated history; live orders are too sparse
        GROUP BY 1, 2""", conn)

# complete grid so missing (day, genre) pairs count as zero demand
grid = pd.MultiIndex.from_product([pd.date_range(df.day.min(), df.day.max()), df.genre.unique()],
                                  names=["day", "genre"])
df["day"] = pd.to_datetime(df.day)
df = df.set_index(["day", "genre"]).reindex(grid, fill_value=0).reset_index().sort_values(["genre", "day"])

g = df.groupby("genre").orders
df["lag1"] = g.shift(1)
df["lag7"] = g.shift(7)
df["mean7"] = g.transform(lambda s: s.shift(1).rolling(7).mean())
df["dow"] = df.day.dt.dayofweek
df["genre_code"] = df.genre.astype("category").cat.codes
df = df.dropna()

cutoff = df.day.max() - pd.Timedelta(days=HOLDOUT_DAYS)
train, test = df[df.day <= cutoff].copy(), df[df.day > cutoff].copy()
feats = ["lag1", "lag7", "mean7", "dow", "genre_code"]


# XGBoost (level): predicts raw orders. Trees can't extrapolate, so when demand
# trends down after training it keeps predicting training-period levels.
level = XGBRegressor(n_estimators=300, max_depth=4, learning_rate=0.05, subsample=0.9, random_state=0)
level.fit(train[feats], train.orders)
pred_level = np.clip(level.predict(test[feats]), 0, None)

# XGBoost (relative): predicts orders / 7-day mean, i.e. the day-of-week multiplier,
# then rescales by the current 7-day mean. The level comes from recent data, the
# model only has to learn the weekly shape, which does not drift.
rel_feats = ["dow", "genre_code", "lag1_rel", "lag7_rel"]
for d in (train, test):
    d["lag1_rel"] = d.lag1 / (d.mean7 + 1)
    d["lag7_rel"] = d.lag7 / (d.mean7 + 1)
rel = XGBRegressor(n_estimators=300, max_depth=3, learning_rate=0.05, subsample=0.9, random_state=0)
rel.fit(train[rel_feats], train.orders / (train.mean7 + 1))
pred = np.clip(rel.predict(test[rel_feats]) * (test.mean7 + 1), 0, None)


def mae(y, p):
    return float(np.mean(np.abs(y - p)))


def wape(y, p):
    return float(np.sum(np.abs(y - p)) / max(np.sum(y), 1))


y = test.orders.values
print(f"holdout days={HOLDOUT_DAYS} rows={len(test)}")
print(f"naive (last week same day) MAE={mae(y, test.lag7.values):.2f}  WAPE={wape(y, test.lag7.values):.1%}")
print(f"7-day mean               MAE={mae(y, test.mean7.values):.2f}  WAPE={wape(y, test.mean7.values):.1%}")
print(f"XGBoost, level target    MAE={mae(y, pred_level):.2f}  WAPE={wape(y, pred_level):.1%}")
print(f"XGBoost, relative target MAE={mae(y, pred):.2f}  WAPE={wape(y, pred):.1%}")
