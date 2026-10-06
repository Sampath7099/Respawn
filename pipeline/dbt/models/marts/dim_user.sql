-- variant: assignment is a pure function of user_id, so all of a user's events carry
-- the same arm. tests/assert_one_variant_per_user.sql fails the build if that breaks.
select user_id,
       min(event_ts) as first_seen_at,
       max(event_ts) as last_seen_at,
       min(event_date) as signup_date,
       date_trunc('week', min(event_date))::date as signup_cohort_week,
       min(variant) as variant
from {{ ref('stg_events') }}
group by 1
