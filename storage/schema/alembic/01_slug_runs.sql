-- slug_runs
-- Source: SlugRunMetaItem (items.py)
-- Written once per spider run in spider.closed().

CREATE TABLE slug_runs (
    id                UUID            PRIMARY KEY DEFAULT gen_random_uuid(),

    -- SlugRunMetaItem fields (1:1)
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
);

CREATE INDEX ix_slug_runs_portal_started_at
    ON slug_runs (portal, started_at DESC);
