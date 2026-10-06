-- Grain: one order.
select order_id, user_id, min(variant) as variant, count(*) as items,
       sum(revenue) as revenue, min(ordered_at) as ordered_at, min(order_date) as order_date
from {{ ref('fct_order_items') }}
group by 1, 2
