select d.date_day,
       count(distinct e.user_id) as dau,
       count(distinct e.session_id) as sessions,
       count(*) filter (where e.event_type = 'purchase') as orders,
       coalesce(sum(o.revenue), 0) as gmv
from {{ ref('dim_date') }} d
left join {{ ref('fct_events') }} e on e.event_date = d.date_day
left join {{ ref('fct_orders') }} o on o.order_id = e.event_id
group by 1
