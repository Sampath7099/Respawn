select user_id, game_id, playtime_forever, playtime_2weeks
from {{ source('raw', 'user_items') }}
where game_id in (select game_id from {{ source('raw', 'games') }})
