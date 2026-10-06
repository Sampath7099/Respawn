-- One clickstream: simulated history + live storefront traffic.
select event_id, user_id, session_id, event_type, game_id, price, variant,
       event_ts, event_ts::date as event_date, 'sim' as source
from {{ source('raw', 'sim_events') }}
union all
select event_id, user_id, session_id, event_type, game_id, price, variant,
       event_ts, event_ts::date as event_date, 'live' as source
from {{ source('raw', 'events') }}
