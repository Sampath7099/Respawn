select e.event_id, e.user_id, e.session_id, e.event_type, e.game_id, e.variant,
       e.event_ts, e.event_date
from {{ ref('stg_events') }} e
