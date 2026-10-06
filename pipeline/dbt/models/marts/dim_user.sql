select user_id,
       min(event_ts) as first_seen_at,
       max(event_ts) as last_seen_at,
       min(event_date) as signup_date,
       date_trunc('week', min(event_date))::date as signup_cohort_week,
       min(variant) as variant
from {{ ref('stg_events') }}
group by 1
