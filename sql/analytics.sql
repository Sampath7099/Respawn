-- Respawn analytics: business questions answered in SQL against the marts schema.
-- Run any block with:  psql -h localhost -p 5433 -U respawn respawn

-- Q1. Conversion funnel: of sessions that viewed a game, how many reached cart and purchase?
WITH s AS (
    SELECT session_id,
           bool_or(event_type = 'game_click')  AS clicked,
           bool_or(event_type = 'add_to_cart') AS carted,
           bool_or(event_type = 'purchase')    AS purchased
    FROM marts.fct_events GROUP BY session_id
)
SELECT count(*)                                              AS sessions,
       count(*) FILTER (WHERE clicked)                       AS clicked,
       count(*) FILTER (WHERE carted)                        AS carted,
       count(*) FILTER (WHERE purchased)                     AS purchased,
       round(100.0 * count(*) FILTER (WHERE purchased)
             / nullif(count(*) FILTER (WHERE carted), 0), 1) AS cart_to_purchase_pct
FROM s;

-- Q2. Weekly cohort retention: % of each signup cohort active N weeks later.
WITH activity AS (
    SELECT DISTINCT u.user_id, u.signup_cohort_week,
           (date_trunc('week', e.event_date)::date - u.signup_cohort_week) / 7 AS week_n
    FROM marts.fct_events e JOIN marts.dim_user u USING (user_id)
)
SELECT signup_cohort_week,
       count(*) FILTER (WHERE week_n = 0) AS cohort_size,
       round(100.0 * count(*) FILTER (WHERE week_n = 1) / nullif(count(*) FILTER (WHERE week_n = 0), 0), 1) AS w1_pct,
       round(100.0 * count(*) FILTER (WHERE week_n = 2) / nullif(count(*) FILTER (WHERE week_n = 0), 0), 1) AS w2_pct,
       round(100.0 * count(*) FILTER (WHERE week_n = 4) / nullif(count(*) FILTER (WHERE week_n = 0), 0), 1) AS w4_pct
FROM activity GROUP BY 1 ORDER BY 1;

-- Q3. Top 3 games by revenue within each genre (window function: top-N per group).
WITH rev AS (
    SELECT g.primary_genre, g.title, sum(o.revenue) AS revenue
    FROM marts.fct_orders o JOIN marts.dim_game g USING (game_id)
    GROUP BY 1, 2
)
SELECT * FROM (
    SELECT *, dense_rank() OVER (PARTITION BY primary_genre ORDER BY revenue DESC) AS rnk FROM rev
) t WHERE rnk <= 3 ORDER BY primary_genre, rnk;

-- Q4. Running GMV and 7-day moving average (window frames).
SELECT date_day, gmv,
       sum(gmv) OVER (ORDER BY date_day)                                         AS running_gmv,
       round(avg(gmv) OVER (ORDER BY date_day ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 2) AS gmv_7d_avg
FROM marts.agg_daily_kpis ORDER BY date_day;

-- Q5. RFM segmentation of buyers (NTILE scoring).
WITH rfm AS (
    SELECT user_id,
           (SELECT max(order_date) FROM marts.fct_orders) - max(order_date) AS recency_days,
           count(*) AS frequency, sum(revenue) AS monetary
    FROM marts.fct_orders GROUP BY user_id
), scored AS (
    SELECT *, ntile(4) OVER (ORDER BY recency_days DESC) AS r,
              ntile(4) OVER (ORDER BY frequency)         AS f,
              ntile(4) OVER (ORDER BY monetary)          AS m
    FROM rfm
)
SELECT CASE WHEN r = 4 AND f >= 3 THEN 'champions'
            WHEN r >= 3 AND f <= 2 THEN 'new / promising'
            WHEN r <= 2 AND f >= 3 THEN 'at risk'
            ELSE 'hibernating' END AS segment,
       count(*) AS users, round(avg(monetary), 2) AS avg_spend
FROM scored GROUP BY 1 ORDER BY users DESC;

-- Q6. Time between a user's purchases (LAG) - how often do buyers come back?
SELECT percentile_cont(ARRAY[0.25, 0.5, 0.75]) WITHIN GROUP (ORDER BY gap_days) AS gap_days_p25_p50_p75
FROM (
    SELECT order_date - lag(order_date) OVER (PARTITION BY user_id ORDER BY ordered_at) AS gap_days
    FROM marts.fct_orders
) t WHERE gap_days IS NOT NULL;

-- Q7. Wishlist -> purchase conversion by price band.
WITH w AS (SELECT DISTINCT user_id, game_id FROM marts.fct_events WHERE event_type = 'wishlist_add'),
     p AS (SELECT DISTINCT user_id, game_id FROM marts.fct_orders)
SELECT g.price_band, count(*) AS wishlisted,
       round(100.0 * count(p.user_id) / count(*), 2) AS converted_pct
FROM w JOIN marts.dim_game g USING (game_id)
LEFT JOIN p USING (user_id, game_id)
GROUP BY 1 ORDER BY 1;

-- Q8. A/B snapshot: conversion and revenue per user by variant.
SELECT u.variant, count(DISTINCT u.user_id) AS users,
       count(DISTINCT o.user_id)            AS buyers,
       round(100.0 * count(DISTINCT o.user_id) / count(DISTINCT u.user_id), 2) AS buyer_rate_pct,
       round(coalesce(sum(o.revenue), 0) / count(DISTINCT u.user_id), 2)       AS revenue_per_user
FROM marts.dim_user u LEFT JOIN marts.fct_orders o USING (user_id)
GROUP BY 1;
