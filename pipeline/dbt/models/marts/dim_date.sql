select d::date as date_day, extract(isodow from d)::int as day_of_week,
       date_trunc('week', d)::date as week_start, to_char(d, 'YYYY-MM') as month
from generate_series((select min(event_date) from {{ ref('stg_events') }}),
                     (select max(event_date) from {{ ref('stg_events') }}), interval '1 day') d
