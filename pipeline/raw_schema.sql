DROP SCHEMA IF EXISTS raw CASCADE;
CREATE SCHEMA raw;

CREATE TABLE raw.games (
    game_id           bigint PRIMARY KEY,
    title             text,
    developer         text,
    publisher         text,
    release_date_text text,
    price             numeric(10,2),
    sentiment         text,
    early_access      boolean
);

CREATE TABLE raw.game_genres (
    game_id bigint,
    genre   text
);

CREATE TABLE raw.users (
    user_id text PRIMARY KEY
);

CREATE TABLE raw.user_items (
    user_id          text,
    game_id          bigint,
    playtime_forever int,
    playtime_2weeks  int
);

CREATE TABLE raw.reviews (
    user_id     text,
    game_id     bigint,
    recommend   boolean,
    posted_text text,
    review_text text
);

-- Simulated storefront clickstream (written by simulator/simulate.py)
CREATE TABLE raw.events (
    event_id   bigint PRIMARY KEY,
    user_id    text NOT NULL,
    session_id text NOT NULL,
    event_type text NOT NULL,
    game_id    bigint,
    price      numeric(10,2),
    variant    text,
    event_ts   timestamptz NOT NULL
);
