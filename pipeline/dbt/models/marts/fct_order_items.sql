-- Grain: one game in one order.
select oi.order_id, oi.user_id, oi.game_id, u.variant, oi.price as revenue,
       oi.ordered_at, oi.ordered_at::date as order_date
from {{ ref('stg_order_items') }} oi
left join {{ ref('dim_user') }} u using (user_id)
