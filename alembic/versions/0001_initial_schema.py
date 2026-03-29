"""initial_schema

Creates all application tables from the items.py source of truth:
  - slug_runs      (from SlugRunMetaItem)
  - slugs          (from SlugCollectionItem, FK → slug_runs)
  - raw_listings   (from RawListingItem — append-only ingest log)
  - listings       (deduplicated canonical records; written by ListingProcessor)
  - price_history  (append-only price observations; written by ListingProcessor)
  - feedback       (user feedback events)
  - report_jobs    (async report job queue)

Revision ID: 0001
Revises:
Create Date: 2026-03-29
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------ trigger
    op.execute("""
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$
    """)

    # ---------------------------------------------------------------- slug_runs
    # Source: SlugRunMetaItem (items.py)
    # Written once per spider run in spider.closed().
    op.execute("""
        CREATE TABLE slug_runs (
            id                UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id            TEXT            NOT NULL UNIQUE,
            portal            TEXT            NOT NULL,
            city              TEXT            NOT NULL,
            started_at        TIMESTAMPTZ     NOT NULL,
            ended_at          TIMESTAMPTZ,
            runtime_seconds   NUMERIC(10, 3),
            completion_reason TEXT,
            parameters        JSONB           NOT NULL DEFAULT '{}',
            total_advertised  INTEGER,
            investments_found INTEGER,
            slug_count        INTEGER         NOT NULL DEFAULT 0
        )
    """)

    op.execute("""
        CREATE INDEX ix_slug_runs_portal_started_at
            ON slug_runs (portal, started_at DESC)
    """)

    # -------------------------------------------------------------------- slugs
    # Source: SlugCollectionItem (items.py)
    # One row per discovered listing URL. Serves as the detail-scrape queue.
    op.execute("""
        CREATE TABLE slugs (
            id              UUID        PRIMARY KEY,
            run_id          TEXT        REFERENCES slug_runs(run_id),
            portal          TEXT        NOT NULL,
            slug            TEXT        NOT NULL,
            full_url        TEXT        NOT NULL UNIQUE,
            first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_scraped_at TIMESTAMPTZ,
            scrape_status   TEXT        NOT NULL DEFAULT 'pending'
        )
    """)

    op.execute("""
        CREATE INDEX ix_slugs_portal_scrape_status
            ON slugs (portal, scrape_status, last_scraped_at)
    """)

    op.execute("""
        CREATE INDEX ix_slugs_run_id
            ON slugs (run_id)
    """)

    # ------------------------------------------------------------ raw_listings
    # Source: RawListingItem (items.py)
    # Append-only ingest log. Every validated spider item lands here.
    # Never updated or deleted. ListingProcessor reads unprocessed rows
    # (processed_at IS NULL) and upserts into listings / price_history.
    op.execute("""
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

            -- Processing lifecycle (set by ListingProcessor)
            processed_at      TIMESTAMPTZ
        )
    """)

    op.execute("""
        CREATE INDEX ix_raw_listings_source_url_scraped_at
            ON raw_listings (source_url, scraped_at DESC)
    """)

    op.execute("""
        CREATE INDEX ix_raw_listings_processed_at
            ON raw_listings (processed_at)
            WHERE processed_at IS NULL
    """)

    # ---------------------------------------------------------------- listings
    # Deduplicated canonical records. Written by ListingProcessor, not by spiders.
    # price_pln / price_per_m2 → price_history (append-only)
    # photo_urls               → NOT stored (transient; pipeline downloads them)
    # http_status / date_scraped → NOT stored (transient scraping metadata)
    op.execute("""
        CREATE TABLE listings (
            id                UUID            PRIMARY KEY DEFAULT gen_random_uuid(),

            source_portal     TEXT            NOT NULL,
            source_url        TEXT            NOT NULL UNIQUE,
            external_id       TEXT,

            title             TEXT            NOT NULL,
            description       TEXT,
            description_length INTEGER,

            city              TEXT            NOT NULL,
            district          TEXT,
            street            TEXT,
            latitude          DOUBLE PRECISION,
            longitude         DOUBLE PRECISION,

            area_m2           NUMERIC(8, 2),
            rooms             INTEGER,
            floor             INTEGER,
            total_floors      INTEGER,
            year_built        INTEGER,

            has_lift          BOOLEAN         NOT NULL DEFAULT false,
            has_balcony       BOOLEAN         NOT NULL DEFAULT false,
            has_terrace       BOOLEAN         NOT NULL DEFAULT false,
            has_storage       BOOLEAN         NOT NULL DEFAULT false,
            has_floor_plan    BOOLEAN         NOT NULL DEFAULT false,
            heating_type      TEXT,
            parking           TEXT,
            has_parking       BOOLEAN         NOT NULL DEFAULT false,
            building_material TEXT,

            property_type     TEXT            NOT NULL,
            market_type       TEXT            NOT NULL,
            listing_type      TEXT            NOT NULL,
            date_posted       TIMESTAMPTZ,

            photo_count       INTEGER         NOT NULL DEFAULT 0,
            photo_paths       TEXT[]          NOT NULL DEFAULT '{}',

            composite_score   NUMERIC(4, 2),

            status            TEXT            NOT NULL DEFAULT 'active',
            first_seen_at     TIMESTAMPTZ     NOT NULL DEFAULT now(),
            last_scraped_at   TIMESTAMPTZ     NOT NULL DEFAULT now(),
            last_scored_at    TIMESTAMPTZ,

            created_at        TIMESTAMPTZ     NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ     NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE INDEX ix_listings_status_last_scraped_at
            ON listings (status, last_scraped_at)
    """)

    op.execute("""
        CREATE INDEX ix_listings_city_composite_score
            ON listings (city, composite_score DESC)
    """)

    op.execute("""
        CREATE INDEX ix_listings_source_portal_external_id
            ON listings (source_portal, external_id)
    """)

    op.execute("""
        CREATE INDEX ix_listings_status_last_scored_at
            ON listings (status, last_scored_at)
    """)

    op.execute("""
        CREATE TRIGGER trg_listings_updated_at
        BEFORE UPDATE ON listings
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)

    # --------------------------------------------------------------- slugs FK
    # Add listing_id FK now that listings table exists.
    op.execute("""
        ALTER TABLE slugs
            ADD COLUMN listing_id UUID REFERENCES listings(id)
    """)

    # ----------------------------------------------------------- price_history
    # Append-only price observations per listing.
    # Never UPDATE — always INSERT a new row on each price change.
    op.execute("""
        CREATE TABLE price_history (
            id           UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
            listing_id   UUID            NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
            price_pln    NUMERIC(12, 2)  NOT NULL,
            price_per_m2 NUMERIC(10, 2),
            observed_at  TIMESTAMPTZ     NOT NULL DEFAULT now(),
            source       TEXT            NOT NULL DEFAULT 'scrape'
        )
    """)

    op.execute("""
        CREATE INDEX ix_price_history_listing_id_observed_at
            ON price_history (listing_id, observed_at DESC)
    """)

    # ---------------------------------------------------------------- feedback
    op.execute("""
        CREATE TABLE feedback (
            id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            listing_id UUID        NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
            action     TEXT        NOT NULL,
            reason     TEXT,
            acted_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # ------------------------------------------------------------- report_jobs
    op.execute("""
        CREATE TABLE report_jobs (
            id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            status     TEXT        NOT NULL DEFAULT 'pending',
            criteria   JSONB       NOT NULL,
            result     JSONB,
            error      TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE INDEX ix_report_jobs_status_created_at
            ON report_jobs (status, created_at)
    """)

    op.execute("""
        CREATE TRIGGER trg_report_jobs_updated_at
        BEFORE UPDATE ON report_jobs
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS report_jobs CASCADE")
    op.execute("DROP TABLE IF EXISTS feedback CASCADE")
    op.execute("DROP TABLE IF EXISTS price_history CASCADE")
    op.execute("ALTER TABLE slugs DROP COLUMN IF EXISTS listing_id")
    op.execute("DROP TABLE IF EXISTS listings CASCADE")
    op.execute("DROP TABLE IF EXISTS raw_listings CASCADE")
    op.execute("DROP TABLE IF EXISTS slugs CASCADE")
    op.execute("DROP TABLE IF EXISTS slug_runs CASCADE")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
