-- A user seen in both A/B arms means assignment is broken: fail the build.
select user_id from {{ ref('stg_events') }} group by 1 having count(distinct variant) > 1
