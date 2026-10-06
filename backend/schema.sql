-- Storefront (OLTP) tables. Catalogue and users come from raw.* (the Steam data).
CREATE SCHEMA IF NOT EXISTS store;

CREATE TABLE IF NOT EXISTS store.wishlist (
    user_id    text NOT NULL,
    game_id    bigint NOT NULL,
    added_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, game_id)
);

CREATE TABLE IF NOT EXISTS store.orders (
    order_id        bigserial PRIMARY KEY,
    user_id         text NOT NULL,
    idempotency_key text NOT NULL,
    total           numeric(10,2) NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, idempotency_key)        -- a retried checkout cannot charge twice
);

CREATE TABLE IF NOT EXISTS store.order_items (
    order_id bigint REFERENCES store.orders,
    game_id  bigint NOT NULL,
    price    numeric(10,2) NOT NULL,
    PRIMARY KEY (order_id, game_id)
);

-- Transactional outbox: events are written in the same transaction as the
-- business change, then relayed to Kafka. No "order saved but event lost".
CREATE TABLE IF NOT EXISTS store.outbox (
    id           bigserial PRIMARY KEY,
    topic        text NOT NULL,
    payload      jsonb NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz
);
CREATE INDEX IF NOT EXISTS outbox_unpublished ON store.outbox (id) WHERE published_at IS NULL;
