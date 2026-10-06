-- Static dataset tables are rebuilt on every ingest. Event tables are created once
-- and never dropped here: raw.events holds live storefront data.
CREATE SCHEMA IF NOT EXISTS raw;

DROP TABLE IF EXISTS raw.games, raw.game_genres, raw.users, raw.user_items, raw.reviews CASCADE;

CREATE TABLE raw.games (
    game_id           bigint PRIMARY KEY,
    title             text,
    developer         text,
    publisher         text,
    release_date_text text,
    price             numeric(10,2),   -- NULL = price not parseable = not for sale
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

-- Live clickstream from the storefront (Kafka consumer, backend/app/relay.py)
CREATE TABLE IF NOT EXISTS raw.events (
    event_id   bigint PRIMARY KEY,
    user_id    text NOT NULL,
    session_id text NOT NULL,
    event_type text NOT NULL,
    game_id    bigint,
    price      numeric(10,2),
    variant    text,
    event_ts   timestamptz NOT NULL
);

-- Simulated clickstream (simulator/simulate.py truncates and refills only this table)
CREATE TABLE IF NOT EXISTS raw.sim_events (LIKE raw.events INCLUDING ALL);
