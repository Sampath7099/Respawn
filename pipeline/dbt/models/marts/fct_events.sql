-- Clickstream enriched with game attributes for slicing (genre, price band).
select e.event_id, e.user_id, e.session_id, e.event_type, e.game_id, e.variant, e.source,
       g.primary_genre, g.price_band, e.event_ts, e.event_date
from {{ ref('stg_events') }} e
left join {{ ref('dim_game') }} g using (game_id)
