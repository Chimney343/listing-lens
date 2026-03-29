-- raw_slugs
-- Source: SlugCollectionItem (items.py)
-- Append-only observation log.  One row per (slug, run_id) pair.
-- Written by DatabasePipeline for every SlugCollectionItem yielded by OtodomSlugSpider.
-- Never updated or deleted.

CREATE TABLE raw_slugs (
    id          UUID        PRIMARY KEY,           -- UUID assigned by spider at collection time
    run_id      TEXT        REFERENCES slug_runs(run_id),
    portal      TEXT        NOT NULL,
    slug        TEXT        NOT NULL,
    full_url    TEXT        NOT NULL,              -- no UNIQUE — same slug recurs across runs
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_raw_slugs_run_id
    ON raw_slugs (run_id);

CREATE INDEX ix_raw_slugs_full_url
    ON raw_slugs (full_url);

CREATE INDEX ix_raw_slugs_portal_run_id
    ON raw_slugs (portal, run_id);


-- slugs (operational queue)
-- One deduplicated row per unique listing URL.
-- Populated by storage.db.refresh_slug_queue(conn), which upserts from raw_slugs.
-- Read by OtodomDetailSpider (DB mode) to find slugs pending scrape.

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
    scrape_status     TEXT        NOT NULL DEFAULT 'pending',  -- pending | scraped | failed | gone
    last_scraped_at   TIMESTAMPTZ,

    -- Set once the listing row exists in listings
    listing_id        UUID        REFERENCES listings(id)
);

CREATE INDEX ix_slugs_portal_scrape_status
    ON slugs (portal, scrape_status, last_scraped_at);
