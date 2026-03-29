-- price_history
-- Source: RawListingItem.price_pln / price_per_m2 (items.py)
--
-- Append-only. Never UPDATE existing rows — always INSERT a new row on each scrape.

CREATE TABLE price_history (
    id           UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    listing_id   UUID            NOT NULL REFERENCES listings(id) ON DELETE CASCADE,

    -- RawListingItem: price_pln, price_per_m2
    price_pln    NUMERIC(12, 2)  NOT NULL,
    price_per_m2 NUMERIC(10, 2),

    -- DB-only
    observed_at  TIMESTAMPTZ     NOT NULL DEFAULT now(),
    source       TEXT            NOT NULL DEFAULT 'scrape'
);

CREATE INDEX ix_price_history_listing_id_observed_at
    ON price_history (listing_id, observed_at DESC);
