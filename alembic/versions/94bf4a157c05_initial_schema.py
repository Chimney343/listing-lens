"""initial_schema

Revision ID: 94bf4a157c05
Revises: 
Create Date: 2026-03-27 13:37:49.156287

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '94bf4a157c05'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all tables, indexes, and the updated_at trigger."""

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

    # ---------------------------------------------------------------- listings
    op.execute("""
        CREATE TABLE listings (
            id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            source_portal     TEXT        NOT NULL,
            source_url        TEXT        NOT NULL UNIQUE,
            external_id       TEXT,
            title             TEXT        NOT NULL,
            description       TEXT,
            city              TEXT        NOT NULL,
            district          TEXT,
            street            TEXT,
            latitude          DOUBLE PRECISION,
            longitude         DOUBLE PRECISION,
            area_m2           NUMERIC(8, 2),
            rooms             INTEGER,
            floor             INTEGER,
            total_floors      INTEGER,
            year_built        INTEGER,
            property_type     TEXT        NOT NULL,
            market_type       TEXT        NOT NULL,
            listing_type      TEXT        NOT NULL,
            heating_type      TEXT,
            building_material TEXT,
            has_lift          BOOLEAN     NOT NULL DEFAULT false,
            has_balcony       BOOLEAN     NOT NULL DEFAULT false,
            has_terrace       BOOLEAN     NOT NULL DEFAULT false,
            has_parking       BOOLEAN     NOT NULL DEFAULT false,
            has_storage       BOOLEAN     NOT NULL DEFAULT false,
            photo_count       INTEGER     NOT NULL DEFAULT 0,
            photo_paths       TEXT[]      NOT NULL DEFAULT '{}',
            composite_score   NUMERIC(4, 2),
            status            TEXT        NOT NULL DEFAULT 'active',
            first_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_scraped_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_scored_at    TIMESTAMPTZ,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
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

    # ----------------------------------------------------------- price_history
    op.execute("""
        CREATE TABLE price_history (
            id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            listing_id   UUID        NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
            price_pln    NUMERIC(12, 2) NOT NULL,
            price_per_m2 NUMERIC(10, 2),
            observed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            source       TEXT        NOT NULL DEFAULT 'scrape'
        )
    """)

    op.execute("""
        CREATE INDEX ix_price_history_listing_id_observed_at
            ON price_history (listing_id, observed_at DESC)
    """)

    # -------------------------------------------------------------------slugs
    op.execute("""
        CREATE TABLE slugs (
            id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            portal         TEXT        NOT NULL,
            slug           TEXT        NOT NULL,
            full_url       TEXT        NOT NULL UNIQUE,
            listing_id     UUID        REFERENCES listings(id),
            first_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_scraped_at TIMESTAMPTZ,
            scrape_status  TEXT        NOT NULL DEFAULT 'pending'
        )
    """)

    op.execute("""
        CREATE INDEX ix_slugs_portal_scrape_status_last_scraped_at
            ON slugs (portal, scrape_status, last_scraped_at)
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
    """Drop all tables and the trigger function."""
    op.execute("DROP TABLE IF EXISTS report_jobs CASCADE")
    op.execute("DROP TABLE IF EXISTS feedback CASCADE")
    op.execute("DROP TABLE IF EXISTS slugs CASCADE")
    op.execute("DROP TABLE IF EXISTS price_history CASCADE")
    op.execute("DROP TABLE IF EXISTS listings CASCADE")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
