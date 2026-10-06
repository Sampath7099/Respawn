select event_id, user_id, session_id, event_type, game_id, price, variant,
       event_ts, event_ts::date as event_date
from {{ source('raw', 'events') }}
