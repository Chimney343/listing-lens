"""split_slugs

Splits the monolithic ``slugs`` table into two:

  * ``raw_slugs`` — append-only observation log.  One row per
    (slug, slug_run) pair.  Written by ``DatabasePipeline`` for
    every ``SlugCollectionItem`` yielded by ``OtodomSlugSpider``.

  * ``slugs`` — operational queue.  One deduplicated row per unique
    listing URL.  Populated / refreshed by calling
    ``storage.db.refresh_slug_queue(conn)``, which upserts from
    ``raw_slugs``.  Read by ``OtodomDetailSpider`` (DB mode).

These two concerns are intentionally decoupled: the slug spider
writes only to ``raw_slugs``; nothing in the scraping layer touches
``slugs`` directly.  ``refresh_slug_queue`` can be called at any
time and is fully idempotent.

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-29
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Strip lifecycle columns from old slugs table ──────────────────────
    # These belong on the new operational queue, not the append-only log.
    op.execute("ALTER TABLE slugs DROP COLUMN listing_id")
    op.execute("ALTER TABLE slugs DROP COLUMN first_seen_at")
    op.execute("ALTER TABLE slugs DROP COLUMN last_scraped_at")
    op.execute("ALTER TABLE slugs DROP COLUMN scrape_status")

    # PostgreSQL auto-names the UNIQUE constraint after the table.
    op.execute("ALTER TABLE slugs DROP CONSTRAINT IF EXISTS slugs_full_url_key")

    # Drop the compound index — scrape_status column no longer exists.
    op.execute("DROP INDEX IF EXISTS ix_slugs_portal_scrape_status")

    # ── 2. Add observed_at (timestamp of this individual observation) ─────────
    op.execute("""
        ALTER TABLE slugs
            ADD COLUMN observed_at TIMESTAMPTZ NOT NULL DEFAULT now()
    """)

    # ── 3. Rename slugs → raw_slugs ──────────────────────────────────────────
    op.execute("ALTER TABLE slugs RENAME TO raw_slugs")
    op.execute("ALTER INDEX IF EXISTS ix_slugs_run_id RENAME TO ix_raw_slugs_run_id")

    # ── 4. Indexes for raw_slugs ──────────────────────────────────────────────
    # full_url index — used by the GROUP BY in refresh_slug_queue's UPSERT.
    op.execute("CREATE INDEX ix_raw_slugs_full_url ON raw_slugs (full_url)")
    # portal + run_id — for tracing which run produced which slugs.
    op.execute("CREATE INDEX ix_raw_slugs_portal_run_id ON raw_slugs (portal, run_id)")

    # ── 5. New operational slugs queue ────────────────────────────────────────
    op.execute("""
        CREATE TABLE slugs (
            id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            portal            TEXT        NOT NULL,
            slug              TEXT        NOT NULL,
            full_url          TEXT        NOT NULL UNIQUE,

            -- Derived from raw_slugs by refresh_slug_queue()
            first_seen_at     TIMESTAMPTZ NOT NULL,
            last_seen_at      TIMESTAMPTZ NOT NULL,
            observation_count INTEGER     NOT NULL DEFAULT 1,

            -- Scrape queue lifecycle — managed by OtodomDetailSpider / ListingProcessor
            scrape_status     TEXT        NOT NULL DEFAULT 'pending',
            last_scraped_at   TIMESTAMPTZ,

            -- Set once the listing row exists in listings
            listing_id        UUID        REFERENCES listings(id)
        )
    """)

    op.execute("""
        CREATE INDEX ix_slugs_portal_scrape_status
            ON slugs (portal, scrape_status, last_scraped_at)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS slugs CASCADE")

    op.execute("DROP INDEX IF EXISTS ix_raw_slugs_full_url")
    op.execute("DROP INDEX IF EXISTS ix_raw_slugs_portal_run_id")

    op.execute("ALTER TABLE raw_slugs RENAME TO slugs")
    op.execute("ALTER INDEX IF EXISTS ix_raw_slugs_run_id RENAME TO ix_slugs_run_id")

    op.execute("ALTER TABLE slugs DROP COLUMN IF EXISTS observed_at")

    # Restore the columns dropped in upgrade step 1.
    op.execute("""
        ALTER TABLE slugs
            ADD COLUMN listing_id     UUID        REFERENCES listings(id),
            ADD COLUMN first_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            ADD COLUMN last_scraped_at TIMESTAMPTZ,
            ADD COLUMN scrape_status  TEXT        NOT NULL DEFAULT 'pending'
    """)
    op.execute("ALTER TABLE slugs ADD CONSTRAINT slugs_full_url_key UNIQUE (full_url)")
    op.execute("""
        CREATE INDEX ix_slugs_portal_scrape_status
            ON slugs (portal, scrape_status, last_scraped_at)
    """)
