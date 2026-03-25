---
applyTo: "**/storage/**,**/db/**,**/models/**,**/photo_storage*,**/database*,**/migrations/**,**/pipelines.py"
---

# Stage 3 — Storage Layer (PostgreSQL + Filesystem)

## Objective

Build the storage layer that persists all scraped listing data, price history, deduplication state, feedback signals, and report jobs. The system is designed to be:

- **Self-hosted first**: Runs entirely on a Raspberry Pi 5 with a 500 GB NVMe. No cloud dependency during development or early production.
- **Migratable by config**: Switching from local to cloud Postgres requires only a `DATABASE_URL` change and a `pg_dump` restore. Switching photo storage from filesystem to S3 requires only swapping the injected `PhotoStorage` implementation. No code changes at migration time.
- **Schema-complete upfront**: Every table, index, constraint, and nullable justification is defined before any pipeline code is written. Late schema changes are expensive; sparse input is handled by nullable fields with documented intent, not by redesigning tables.
- **Injection-friendly**: Database connections and the photo storage implementation are injected into every component that needs them. No module-level singletons. This is required for testability and for clean separation between the scraper process, the worker process, and the API process.
- **Observable**: Every write operation is logged at the boundary with structured key-value context. Bulk operations report row counts. Failed writes surface the offending record and the exception cause without swallowing either.

The storage layer is the hand-off point between the scraping stage (Stage 1) and all downstream stages (deduplication, scoring, freshness, feedback, API). Its contracts — table schemas, the `PhotoStorage` protocol, and the connection factory — are consumed by every subsequent stage.

---

## Dependencies

- **psycopg** (≥3.1, the v3 async-capable library, not psycopg2) — primary DB driver. Use the synchronous connection API in the scraper pipeline (Scrapy is not async-native); use the async API in the FastAPI layer.
- **psycopg-pool** (≥3.1) — connection pooling for the API and worker processes. The scraper pipeline uses a single synchronous connection per run, not a pool.
- **alembic** (≥1.13) — schema migrations. All schema changes go through Alembic; no ad-hoc `ALTER TABLE` in production.
- **pydantic** (≥2.9) — data models that cross module boundaries. The `StoredListing` and `ReportJob` models are defined here and imported by downstream stages.
- **pydantic-settings** (≥2.4) — typed config; `DATABASE_URL` and `PHOTO_STORAGE_*` vars live in the settings model.
- **boto3** (≥1.34) — S3 client for the `S3PhotoStorage` implementation. Only imported if `PHOTO_STORAGE_BACKEND=s3` in config. Not a required dependency at local phase.
- **structlog** (≥24.1) — structured logging throughout.

All dependencies managed by Poetry. `boto3` is an optional dependency group (`storage-s3`) so it is not installed in local-only deployments.

---

## Hardware Context

Storage runs on a Raspberry Pi 5 with 8 GB RAM and a 500 GB NVMe drive connected via PCIe gen 2. The NVMe delivers ~400–450 MB/s sequential and high random IOPS — it is not the bottleneck. The SD card is not used for any database or photo data.

**Postgres data directory must be on the Pi's NVMe mount.** On this machine the NVMe drive is mounted at `/mnt/nvme`, and the default `/var/lib/postgresql/` path still points to the SD card after a standard install. Before initialising any schema, the data directory must be moved:

Stop the service, move the directory to the NVMe mount (e.g. `/mnt/nvme/postgresql`), create a symlink at the original path pointing to the new location, then restart. Verify with `SHOW data_directory;` inside psql before proceeding.

**Postgres tuning** — set these in `postgresql.conf` before running any pipeline load:

`shared_buffers = 2GB`, `effective_cache_size = 6GB`, `work_mem = 64MB`, `maintenance_work_mem = 512MB`, `max_connections = 20`, `wal_buffers = 64MB`, `random_page_cost = 1.1` (NVMe — random and sequential cost are near-equal), `effective_io_concurrency = 256` (NVMe handles deep queue depth).

`max_connections = 20` is intentional. Three processes connect to the DB: the scraper (1 connection), the worker (1–2 connections), and FastAPI (pool of up to 10). Twenty is sufficient with headroom for psql sessions during development. Higher values waste shared memory.

---

## Database Schema

### Design Principles

Every table has an explicit primary key strategy stated below. Foreign keys are named for their referencing intent. Nullable fields have a written justification — absence of data must mean something specific, not "we weren't sure." All timestamps use `timestamptz`. Indexes are specified here, not added later when queries turn slow.

### `listings` table

The central table. One row per unique real-world property listing. Deduplication (Stage 2) determines what "unique" means — the storage layer receives already-deduplicated records.

Primary key: `id UUID DEFAULT gen_random_uuid()`. UUIDs avoid auto-increment coordination problems if the pipeline ever runs on multiple machines.

Fields, types, and nullable justifications:

`source_portal TEXT NOT NULL` — which portal this record originated from (`otodom`, `gratka`, `morizon`). Never null; a listing without a source is untrackable.

`source_url TEXT NOT NULL UNIQUE` — canonical URL of the listing on the source portal. Unique constraint enforces one row per URL; the deduplication engine uses this for exact-match detection before fuzzy matching.

`external_id TEXT` — the portal's own ID for this listing. Nullable: not all portals expose a stable external ID. When present, used as a secondary deduplication signal.

`title TEXT NOT NULL` — listing headline. Required by the validation pipeline; no listing reaches storage without one.

`description TEXT` — full listing description. Nullable: rare but possible for listings that pass validation on title + price alone.

`city TEXT NOT NULL` — normalised city name. Always present; search is city-scoped.

`district TEXT` — neighbourhood or district. Nullable: many listings outside Kraków do not specify district.

`street TEXT` — street address. Nullable: sellers frequently omit street for privacy.

`latitude DOUBLE PRECISION` — nullable: not all portals geocode listings.

`longitude DOUBLE PRECISION` — nullable: paired with latitude; both null or both populated.

`area_m2 NUMERIC(8,2)` — usable floor area. Nullable: some listings omit area (land plots, unusual property types). The validation pipeline requires at least one of `area_m2` or `price_pln`; area alone is never guaranteed.

`rooms INTEGER` — room count. Nullable: omitted on some listing types.

`floor INTEGER` — floor number (0 = ground). Nullable: not applicable to houses; frequently omitted.

`total_floors INTEGER` — total floors in building. Nullable: same reasons as `floor`.

`year_built INTEGER` — nullable: frequently missing on secondary market listings.

`property_type TEXT NOT NULL` — controlled vocabulary: `apartment`, `house`, `studio`, `plot`, `commercial`. Not null; the spider normalises this at parse time.

`market_type TEXT NOT NULL` — `PRIMARY` or `SECONDARY`. Not null.

`listing_type TEXT NOT NULL` — `private` or `agency`. Not null.

`heating_type TEXT` — nullable: highly variable across portals and listing types.

`building_material TEXT` — nullable: frequently omitted.

`has_lift BOOLEAN NOT NULL DEFAULT false` — false when not stated; "not stated" and "confirmed absent" are treated identically for scoring purposes. Documented assumption.

`has_balcony BOOLEAN NOT NULL DEFAULT false` — same rationale.

`has_terrace BOOLEAN NOT NULL DEFAULT false` — same rationale.

`has_parking BOOLEAN NOT NULL DEFAULT false` — same rationale.

`has_storage BOOLEAN NOT NULL DEFAULT false` — same rationale.

`photo_count INTEGER NOT NULL DEFAULT 0` — number of photos available. Zero is valid (listing with no photos).

`photo_paths TEXT[]` — array of storage keys for downloaded photos. Empty array until `PhotoDownloadPipeline` runs. Nullable fields in source data (`photo_urls`) are normalised to an empty array at ingest, never null in the DB.

`composite_score NUMERIC(4,2)` — nullable: populated by Stage 5 scoring. Null means "not yet scored", which is distinct from a score of zero.

`status TEXT NOT NULL DEFAULT 'active'` — `active`, `gone`, `price_changed`. The freshness checker (Stage 4) updates this field.

`first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()` — when this listing first entered the pipeline.

`last_scraped_at TIMESTAMPTZ NOT NULL DEFAULT now()` — when the detail spider last successfully visited this URL. Used by the freshness scheduler to determine re-check priority.

`last_scored_at TIMESTAMPTZ` — nullable: when the LLM scorer last processed this listing. Null means unscored.

`created_at TIMESTAMPTZ NOT NULL DEFAULT now()` — row creation time.

`updated_at TIMESTAMPTZ NOT NULL DEFAULT now()` — updated by a trigger on every write. Used for cache invalidation and audit.

**Indexes on `listings`:**
- `(status, last_scraped_at)` — freshness checker query: find active listings not re-checked recently.
- `(city, composite_score DESC)` — primary browsing query: listings in a city ordered by score.
- `(source_portal, external_id)` — deduplication lookup by portal + external ID.
- `(status, last_scored_at)` — scoring queue query: find active listings not yet scored.

### `price_history` table

Append-only. One row per observed price point per listing. Never update or delete rows in this table.

Primary key: `id UUID DEFAULT gen_random_uuid()`.

`listing_id UUID NOT NULL REFERENCES listings(id) ON DELETE CASCADE` — if a listing is deleted, its price history goes with it.

`price_pln NUMERIC(12,2) NOT NULL` — observed price in PLN at this point in time.

`price_per_m2 NUMERIC(10,2)` — nullable: derived from price / area, but area may be null for some listings. Stored redundantly to avoid recomputation in queries.

`observed_at TIMESTAMPTZ NOT NULL DEFAULT now()` — when this price was recorded.

`source TEXT NOT NULL DEFAULT 'scrape'` — `scrape` (from spider) or `manual` (future). Distinguishes pipeline-generated records from any manual corrections.

**Index on `price_history`:** `(listing_id, observed_at DESC)` — the primary access pattern is "most recent prices for a given listing."

### `slugs` table

Used by the slug spiders to track what has been collected and by the detail spiders to know what to visit. This table is the hand-off point between the slug and detail spider phases.

Primary key: `id UUID DEFAULT gen_random_uuid()`.

`portal TEXT NOT NULL` — which portal this slug belongs to.

`slug TEXT NOT NULL` — the portal's URL slug or path segment for this listing.

`full_url TEXT NOT NULL UNIQUE` — the fully constructed URL. Unique constraint prevents duplicate slug collection entries.

`listing_id UUID REFERENCES listings(id)` — nullable: null until the detail spider has successfully scraped and stored this slug as a listing.

`first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()`.

`last_scraped_at TIMESTAMPTZ` — nullable: null until first successful detail scrape.

`scrape_status TEXT NOT NULL DEFAULT 'pending'` — `pending`, `scraped`, `failed`, `gone`.

**Index on `slugs`:** `(portal, scrape_status, last_scraped_at)` — detail spider query: find pending or stale slugs for a given portal.

### `feedback` table

Populated by Stage 6. One row per user feedback event on a listing.

Primary key: `id UUID DEFAULT gen_random_uuid()`.

`listing_id UUID NOT NULL REFERENCES listings(id) ON DELETE CASCADE`.

`action TEXT NOT NULL` — controlled vocabulary: `viewed`, `dismissed`, `applied`. These are the three feedback signals the CLI captures.

`reason TEXT` — nullable: free-text reason, most useful on `dismissed` actions.

`acted_at TIMESTAMPTZ NOT NULL DEFAULT now()`.

### `report_jobs` table

Populated by the API layer (Stage 7). One row per user-requested report.

Primary key: `id UUID DEFAULT gen_random_uuid()`.

`status TEXT NOT NULL DEFAULT 'pending'` — `pending`, `processing`, `complete`, `failed`.

`criteria JSONB NOT NULL` — the filter parameters the user submitted (city, price range, area range, room count, etc.). Stored as JSONB so the worker can reconstruct the query without schema changes when new filter dimensions are added.

`result JSONB` — nullable: null until the worker completes successfully. Contains the assembled report as structured JSON.

`error TEXT` — nullable: populated on `failed` status. Contains the exception message and traceback summary. Never null when status is `failed`.

`created_at TIMESTAMPTZ NOT NULL DEFAULT now()`.

`updated_at TIMESTAMPTZ NOT NULL DEFAULT now()` — updated by trigger; the API polls this to detect completion.

**Index on `report_jobs`:** `(status, created_at)` — worker poll query: find oldest pending jobs first.

### Triggers

An `updated_at` trigger is required on `listings` and `report_jobs`. Define a single trigger function that sets `NEW.updated_at = now()` and attach it to both tables with `BEFORE UPDATE FOR EACH ROW`. Alembic should manage this trigger as a migration step.

---

## PhotoStorage Abstraction

Photos are the only part of the storage layer that changes between local and cloud deployments. Everything else — DB schema, connection strings, Alembic migrations — is identical. The abstraction boundary is a `Protocol` class.

### The Protocol

`PhotoStorage` defines two methods: `put(key: str, data: bytes) -> str` returns the key under which the photo was stored (always the same as the input key; the return value is for call-site convenience). `get(key: str) -> bytes` retrieves photo bytes by key.

The key format is always `{portal}/{external_id}/{filename}.jpg`, regardless of backend. This mirrors S3 object key conventions so that a local key and an S3 key are structurally identical. Migration from filesystem to S3 is an `aws s3 sync` command plus a config change, not a key remapping operation.

### `FilesystemPhotoStorage`

The local implementation. Accepts a `base_path: Path` at construction (the NVMe mount point, e.g. `/mnt/nvme/photos`). `put` writes bytes to `base_path / key`, creating parent directories as needed. `get` reads and returns the file at `base_path / key`. Raises `FileNotFoundError` (not a generic exception) if the key does not exist. This is a concrete, testable class with no external dependencies.

### `S3PhotoStorage`

The cloud migration implementation. Accepts a configured `boto3` S3 client, a bucket name, and an optional key prefix at construction. `put` calls `s3.put_object`. `get` calls `s3.get_object` and reads the body. Raises `KeyError` (wrapping the boto3 `NoSuchKey` error) if the key does not exist, matching the filesystem implementation's failure mode. This implementation is only instantiated when `PHOTO_STORAGE_BACKEND=s3` in config.

### Injection

Neither implementation is imported directly by the pipeline or the API. A factory function in `storage/factory.py` reads `PHOTO_STORAGE_BACKEND` from settings and returns the appropriate concrete instance. All components that need photo storage receive it as a constructor argument typed as `PhotoStorage`. This makes both implementations substitutable in tests with a trivial in-memory fake.

---

## Connection Management

### Scraper process

The Scrapy `DatabasePipeline` uses a single synchronous `psycopg` connection opened when the spider opens and closed when the spider closes. Connection parameters come from `settings.DATABASE_URL`. No pool — Scrapy is single-threaded in its pipeline execution; a pool adds overhead with no benefit.

The pipeline's `open_spider` method opens the connection and begins a transaction. `close_spider` commits on success or rolls back on exception. Individual item writes use `executemany` for bulk efficiency when processing batches of listings from a single run.

### Worker and API processes

Both use `psycopg_pool.ConnectionPool` with a minimum of 1 and maximum of 5 connections. The pool is created once at process startup and injected into all handlers. The pool is closed at process shutdown via a lifespan context manager (FastAPI) or a shutdown hook (worker).

Using `psycopg` v3 throughout — not psycopg2. The v3 API has native async support, better type safety, and active maintenance. `psycopg2` is not a dependency in this project.

---

## Migrations

Alembic manages all schema changes. The initial migration creates all tables, indexes, and the `updated_at` trigger function in a single revision. Subsequent migrations are additive — no destructive changes without an explicit data migration step in the same revision.

The Alembic `env.py` reads `DATABASE_URL` from the same pydantic-settings config used by the application. There is no separate Alembic-specific config for the connection string.

Migration workflow: `alembic revision --autogenerate -m "description"` to generate, `alembic upgrade head` to apply, `alembic downgrade -1` to roll back one step. All generated migration files are committed to version control; the production DB is never ahead of or behind the codebase's migration history.

Before running migrations on the Pi for the first time, verify the data directory is on the NVMe (`SHOW data_directory;`) and that the tuning parameters are applied (`SHOW shared_buffers;`).

---

## Scrapy Pipeline Updates

Stage 1 left two pipeline stubs: `PhotoDownloadPipeline` and `DatabasePipeline`. Both are implemented in Stage 3.

### `PhotoDownloadPipeline`

Receives a `PhotoStorage` instance via dependency injection (passed through Scrapy's `from_crawler` classmethod reading from settings). For each `RawListingItem`, iterates `photo_urls`, fetches each URL with a plain `httpx` GET (not via Scrapy's download machinery — photos are fetched synchronously outside the crawl loop to avoid interfering with throttle settings), and calls `photo_storage.put(key, data)`. Replaces `photo_urls` with the list of stored keys in `photo_paths`. On per-photo fetch failure: logs the error with the URL and listing ID as context, skips that photo, continues. Does not drop the item for a partial photo failure. Drops the item only if zero photos are successfully stored and `photo_count > 0` (indicating photos were expected but none retrieved) — this is logged as a warning, not a hard failure.

### `DatabasePipeline`

Receives a `psycopg` connection via dependency injection. Maps `RawListingItem` fields to the `listings` schema. Performs an upsert on `source_url` (the unique key): `INSERT ... ON CONFLICT (source_url) DO UPDATE SET ...`. This means re-scraping a listing updates it in place rather than creating a duplicate. After upserting the listing, inserts a row into `price_history` if `price_pln` is present and differs from the most recent recorded price for this listing. Both writes happen in the same transaction.

On `psycopg.errors.UniqueViolation`: this should not occur given the upsert pattern, but if it does, log and skip — do not crash the pipeline.

On any other DB exception: log with full context (listing URL, exception type, message), write the item to `rejected_{portal}.jsonl` with a `db_error` reason, and re-raise to trigger Scrapy's drop mechanism. Do not silently swallow DB errors.

---

## Cloud Migration Procedure

When ready to move from Pi to cloud, the procedure is:

Dump the Postgres database: `pg_dump -Fc listing_lens > listing_lens_$(date +%Y%m%d).dump`. Transfer the dump to the target host. Restore: `pg_restore -d listing_lens listing_lens_YYYYMMDD.dump`. This preserves all data, indexes, triggers, and sequences.

Sync photos to S3: `aws s3 sync /mnt/nvme/photos/ s3://{bucket}/photos/ --storage-class STANDARD_IA`. Keys are identical between filesystem and S3; no remapping needed.

Update config: set `DATABASE_URL` to the new Postgres host, set `PHOTO_STORAGE_BACKEND=s3`, set `S3_BUCKET`, `S3_REGION`, and credentials. Redeploy all three systemd services (or Docker containers on the VPS) pointing at the new config. No code changes.

The Pi's Postgres and photo directory can remain as a warm backup for as long as desired. Run the scraper from either location; the DB is the source of truth either way.

---

## Known Risks

| Risk | Mitigation |
|------|------------|
| SD card used for Postgres data directory due to missed setup step. | Verify with `SHOW data_directory;` before running any migrations. Add a startup assertion in the application that checks the data directory path and refuses to start if it resolves to a non-NVMe mount. |
| `photo_paths` grows unbounded as listings are re-scraped; old photo files accumulate on NVMe. | Implement a cleanup job (Stage 4 or later) that removes photo files for listings with `status = 'gone'` and no recent feedback. Not urgent at early scale. |
| Alembic migration run against wrong database (e.g. a dev DB pointed at production `DATABASE_URL`). | Always print `DATABASE_URL` host at the start of `alembic upgrade head` and require manual confirmation before applying to a production host. Add this to the migration runbook. |
| `psycopg` v3 is not compatible with some libraries that assume psycopg2 internals. | Audit all third-party libraries for psycopg2 assumptions before adding them. Known safe: SQLAlchemy 2.x, Alembic 1.13+, FastAPI. |
| NVMe mount not present at boot before Postgres starts. | Ensure the NVMe mount is defined in `/etc/fstab` and that the `postgresql.service` systemd unit declares `RequiresMountsFor=/mnt/nvme`. |
| Report job worker and scraper pipeline write to the same `listings` table concurrently. | Both use psycopg's default `READ COMMITTED` isolation. Upserts on `source_url` are atomic. No additional locking needed at this scale. |

---

## Testing Approach

- **Unit tests** — `FilesystemPhotoStorage` with a `tmp_path` fixture: verify `put` creates the file at the correct path, `get` returns the same bytes, `get` on a missing key raises `FileNotFoundError`. `DatabasePipeline` with a test DB and a transaction that is rolled back after each test: verify upsert creates a listing on first call, updates on second call with changed price, inserts a `price_history` row only when price changes.
- **Integration tests** — spin up a real Postgres instance (via Docker in CI, or a local test DB on the Pi) and run the full pipeline against a fixture `output.jsonl` from Stage 1. Assert row counts in `listings` and `price_history` match expectations.
- **Migration tests** — run `alembic upgrade head` against a blank DB, assert all tables and indexes exist, run `alembic downgrade base`, assert all tables are gone. This catches migration script errors before they reach production.
- **Minimum viable test surface per component**: happy path (valid item, successful write), missing optional field (nullable fields handled without exception), DB unavailable (connection refused raises a domain exception, not a bare `psycopg` error).
