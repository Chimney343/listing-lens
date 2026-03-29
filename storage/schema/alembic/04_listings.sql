-- listings
-- Source: RawListingItem (items.py)
--
-- Fields NOT stored here:
--   price_pln / price_per_m2  → price_history (append-only, see 04_price_history.sql)
--   photo_urls                → NOT persisted (transient remote URLs; pipeline downloads them)
--   http_status               → NOT persisted (transient scraping metadata)
--   date_scraped              → written to last_scraped_at on upsert

CREATE TABLE listings (
    id                UUID            PRIMARY KEY DEFAULT gen_random_uuid(),

    -- RawListingItem: source_portal, source_url, external_id
    source_portal     TEXT            NOT NULL,
    source_url        TEXT            NOT NULL UNIQUE,
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

    -- RawListingItem: area_m2, rooms, floor, total_floors, year_built
    area_m2           NUMERIC(8, 2),
    rooms             INTEGER,
    floor             INTEGER,
    total_floors      INTEGER,
    year_built        INTEGER,

    -- RawListingItem: has_lift, has_balcony, has_terrace, has_storage,
    --                 has_floor_plan, heating_type, parking, building_material
    has_lift          BOOLEAN         NOT NULL DEFAULT false,
    has_balcony       BOOLEAN         NOT NULL DEFAULT false,
    has_terrace       BOOLEAN         NOT NULL DEFAULT false,
    has_storage       BOOLEAN         NOT NULL DEFAULT false,
    has_floor_plan    BOOLEAN         NOT NULL DEFAULT false,
    heating_type      TEXT,
    parking           TEXT,
    building_material TEXT,
    has_parking       BOOLEAN         NOT NULL DEFAULT false,

    -- RawListingItem: property_type, market_type, listing_type, date_posted
    property_type     TEXT            NOT NULL,
    market_type       TEXT            NOT NULL,
    listing_type      TEXT            NOT NULL,
    date_posted       TIMESTAMPTZ,

    -- RawListingItem: photo_count, photo_paths
    photo_count       INTEGER         NOT NULL DEFAULT 0,
    photo_paths       TEXT[]          NOT NULL DEFAULT '{}',

    -- DB-only: scoring, lifecycle
    composite_score   NUMERIC(4, 2),
    status            TEXT            NOT NULL DEFAULT 'active',
    first_seen_at     TIMESTAMPTZ     NOT NULL DEFAULT now(),
    last_scraped_at   TIMESTAMPTZ     NOT NULL DEFAULT now(),
    last_scored_at    TIMESTAMPTZ,
    created_at        TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX ix_listings_status_last_scraped_at
    ON listings (status, last_scraped_at);

CREATE INDEX ix_listings_city_composite_score
    ON listings (city, composite_score DESC);

CREATE INDEX ix_listings_source_portal_external_id
    ON listings (source_portal, external_id);

CREATE INDEX ix_listings_status_last_scored_at
    ON listings (status, last_scored_at);

CREATE TRIGGER trg_listings_updated_at
BEFORE UPDATE ON listings
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
