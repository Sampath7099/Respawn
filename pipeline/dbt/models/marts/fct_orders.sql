-- price on the event can be missing; fall back to the catalogue price
select e.event_id as order_id, e.user_id, e.game_id, e.variant,
       coalesce(e.price, g.price, 0) as revenue,
       e.event_ts as ordered_at, e.event_date as order_date
from {{ ref('stg_events') }} e
left join {{ ref('stg_games') }} g using (game_id)
where e.event_type = 'purchase'
