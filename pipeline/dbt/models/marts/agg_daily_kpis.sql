with traffic as (
    select event_date, count(distinct user_id) as dau, count(distinct session_id) as sessions
    from {{ ref('fct_events') }} group by 1
), sales as (
    select order_date, count(*) as orders, sum(items) as items_sold, sum(revenue) as gmv
    from {{ ref('fct_orders') }} group by 1
)
select d.date_day,
       coalesce(t.dau, 0) as dau, coalesce(t.sessions, 0) as sessions,
       coalesce(s.orders, 0) as orders, coalesce(s.items_sold, 0) as items_sold,
       coalesce(s.gmv, 0) as gmv
from {{ ref('dim_date') }} d
left join traffic t on t.event_date = d.date_day
left join sales s on s.order_date = d.date_day
