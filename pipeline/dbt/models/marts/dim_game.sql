{{ config(post_hook=['create index if not exists dim_game_owners on {{ this }} (owners desc, game_id)']) }}

with genres as (
    select game_id,
           string_agg(replace(genre, '&amp;', '&'), ', ' order by genre) as genres,
           min(replace(genre, '&amp;', '&')) filter (where genre not in ('Indie', 'Free to Play', 'Early Access')) as primary_genre
    from {{ source('raw', 'game_genres') }}
    group by 1
), owners as (
    select game_id, count(*) as owners, sum(playtime_forever) / 60.0 as total_hours
    from {{ ref('stg_user_items') }} group by 1
), reviews as (
    select game_id, count(*) as review_count, avg(recommend::int) as recommend_rate
    from {{ source('raw', 'reviews') }} group by 1
)
select g.*, coalesce(ge.primary_genre, 'Other') as primary_genre, ge.genres,
       coalesce(o.owners, 0) as owners, coalesce(o.total_hours, 0) as total_hours,
       coalesce(r.review_count, 0) as review_count, r.recommend_rate,
       case when g.price is null then 'not for sale' when g.price = 0 then 'free'
            when g.price < 10 then '<$10' when g.price < 30 then '$10-30' else '$30+' end as price_band
from {{ ref('stg_games') }} g
left join genres ge using (game_id)
left join owners o using (game_id)
left join reviews r using (game_id)
