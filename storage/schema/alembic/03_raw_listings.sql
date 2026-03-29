-- raw_listings
-- Source: RawListingItem (items.py)
--
-- Append-only ingest log. The Scrapy DatabasePipeline writes every validated
-- item here and nowhere else. Never updated or deleted — permanent audit log.
--
-- Fields stored verbatim from RawListingItem; processed_at is set by
-- ListingProcessor (Stage 2) once the row has been promoted to listings.
--
-- Fields NOT stored in listings (kept here only):
--   photo_urls    → transient remote URLs (spider field)
--   http_status   → transient scraping metadata
--   price_pln / price_per_m2 → stored here; ListingProcessor writes to price_history

CREATE TABLE raw_listings (
    id                UUID            PRIMARY KEY DEFAULT gen_random_uuid(),

    -- RawListingItem: source_portal, source_url, external_id
    source_portal     TEXT            NOT NULL,
    source_url        TEXT            NOT NULL,
    external_id       TEXT,

    -- RawListingItem: title, description, description_length
    title             TEXT            NOT NULL,
    description       TEXT,
    description_length INTEGER,

    -- RawListingItem: city, district, street, latitude, longitude
    city              TEXT            NOT NULL,
    district          TEXT,
    street            TEXT,
    latitude          DOUBLE PRECISION,
    longitude         DOUBLE PRECISION,

    -- RawListingItem: price_pln, price_per_m2
    price_pln         NUMERIC(12, 2),
    price_per_m2      NUMERIC(10, 2),

    -- RawListingItem: area_m2, rooms, floor, total_floors, year_built
    area_m2           NUMERIC(8, 2),
    rooms             INTEGER,
    floor             INTEGER,
    total_floors      INTEGER,
    year_built        INTEGER,

    -- RawListingItem: has_lift, has_balcony, has_terrace, has_storage,
    --                 has_floor_plan, heating_type, parking, building_material
    has_lift          BOOLEAN,
    has_balcony       BOOLEAN,
    has_terrace       BOOLEAN,
    has_storage       BOOLEAN,
    has_floor_plan    BOOLEAN,
    heating_type      TEXT,
    parking           TEXT,
    has_parking       BOOLEAN,
    building_material TEXT,

    -- RawListingItem: property_type, market_type, listing_type, date_posted
    property_type     TEXT            NOT NULL,
    market_type       TEXT            NOT NULL,
    listing_type      TEXT            NOT NULL,
    date_posted       TIMESTAMPTZ,

    -- RawListingItem: photo_urls, photo_count, photo_paths
    photo_urls        TEXT[]          NOT NULL DEFAULT '{}',
    photo_count       INTEGER         NOT NULL DEFAULT 0,
    photo_paths       TEXT[]          NOT NULL DEFAULT '{}',

    -- RawListingItem: http_status, date_scraped
    http_status       INTEGER,
    scraped_at        TIMESTAMPTZ     NOT NULL DEFAULT now(),

    -- Processing lifecycle (set by ListingProcessor — Stage 2)
    processed_at      TIMESTAMPTZ
);

CREATE INDEX ix_raw_listings_source_url_scraped_at
    ON raw_listings (source_url, scraped_at DESC);

-- Partial index: unprocessed rows only — used by ListingProcessor
CREATE INDEX ix_raw_listings_processed_at
    ON raw_listings (processed_at)
    WHERE processed_at IS NULL;
