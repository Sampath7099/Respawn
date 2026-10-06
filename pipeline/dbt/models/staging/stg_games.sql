select
    game_id,
    title,
    developer,
    publisher,
    case when release_date_text ~ '^\d{4}-\d{2}-\d{2}$' then release_date_text::date end as release_date,
    coalesce(price, 0)::numeric(10,2) as price,
    sentiment,
    early_access
from {{ source('raw', 'games') }}
where title is not null
