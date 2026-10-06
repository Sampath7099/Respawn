-- One row per game sold. Live orders come from the store's own tables (source of
-- truth). The simulator has no order table, so each simulated purchase is a 1-item order.
select 'sim-' || event_id as order_id, user_id, game_id, price, event_ts as ordered_at
from {{ source('raw', 'sim_events') }}
where event_type = 'purchase'
union all
select 'live-' || o.order_id, o.user_id, oi.game_id, oi.price, o.created_at
from {{ source('store', 'orders') }} o
join {{ source('store', 'order_items') }} oi using (order_id)
