# Permanent Service Design for Listing Lens

## 1. Review of OtodomSpider

### Strengths
- **Modular design**: Separates slug collection (Phase 1) and detail scraping (Phase 2).
- **Investment handling**: Detects investment listings and expands them into unit slugs via API or HTML fallback.
- **Playwright integration**: Uses browser automation for JavaScript‑rendered content and API interception.
- **Anti‑detection measures**: Leverages `scrapy‑impersonate`, randomized delays, and realistic browser contexts.
- **Run‑level isolation**: Each spider instance creates a timestamped directory for logs, slug lists, and output files.
- **Configurable via `OtodomSpiderConfig`**: Supports file‑based configuration for search parameters.

### Areas for Improvement
- **Monolithic class**: At ~570 lines, `OtodomSpider` mixes slug collection, investment expansion, detail parsing, and file I/O.
- **Tight coupling with file system**: Slugs are persisted as JSONL in the run directory, not in a shared database.
- **No built‑in deduplication across runs**: The spider does not remember previously seen slugs; each run starts fresh.
- **Hard‑coded pipeline stubs**: `DatabasePipeline` and `PhotoDownloadPipeline` are empty; storage logic is deferred.
- **Scheduling is external**: The spider expects to be launched manually or via cron; no internal scheduler.

### Design‑Pattern Alignment
- **Single Responsibility**: The spider currently handles too many concerns (URL building, slug collection, investment expansion, detail parsing, file I/O). **Recommendation**: Split into separate spiders or compose reusable components.
- **Separation of Concerns**: Move slug storage and listing persistence to dedicated storage layers (PostgreSQL, MinIO). The spider should only produce items; pipelines should handle storage.
- **Composition over Inheritance**: Favor helper classes (e.g., `SlugManager`, `InvestmentExpander`) that can be injected into spiders, rather than inheriting from a base spider that adds behavior.

---

## 2. Database Schema

We need a central PostgreSQL database to store search configurations, slugs, and listing details.

### 2.1 `search_configurations`
Stores each distinct set of search parameters (city, property type, price range, etc.). One configuration can be used by many slug‑collection runs.

| Column | Type | Description |
|--------|------|-------------|
| `id` | `SERIAL` PRIMARY KEY | |
| `city` | `VARCHAR(100)` | |
| `voivodeship` | `VARCHAR(100)` | |
| `powiat` | `VARCHAR(100)` | |
| `gmina` | `VARCHAR(100)` | |
| `property_type` | `VARCHAR(50)` | `mieszkanie`, `dom`, `dzialka`, etc. |
| `districts` | `VARCHAR[]` | Array of district slugs (empty = all) |
| `price_min` | `INTEGER` NULL | |
| `price_max` | `INTEGER` NULL | |
| `area_min` | `FLOAT` NULL | |
| `area_max` | `FLOAT` NULL | |
| `rooms_min` | `INTEGER` NULL | |
| `rooms_max` | `INTEGER` NULL | |
| `max_pages` | `INTEGER` NULL | |
| `created_at` | `TIMESTAMPTZ` DEFAULT NOW() | |
| `updated_at` | `TIMESTAMPTZ` DEFAULT NOW() | |

### 2.2 `slugs`
Tracks every slug discovered for a given configuration.

| Column | Type | Description |
|--------|------|-------------|
| `id` | `SERIAL` PRIMARY KEY | |
| `config_id` | `INTEGER` REFERENCES `search_configurations(id)` | |
| `slug` | `VARCHAR(200)` NOT NULL | Unique slug string (within config) |
| `discovered_at` | `TIMESTAMPTZ` DEFAULT NOW() | First time this slug was seen |
| `last_seen_at` | `TIMESTAMPTZ` DEFAULT NOW() | Most recent run where slug appeared |
| `is_active` | `BOOLEAN` DEFAULT TRUE | False after 3 consecutive absences |
| `last_scraped_at` | `TIMESTAMPTZ` NULL | When detail page was last scraped |
| `scrape_count` | `INTEGER` DEFAULT 0 | Number of times detail page was scraped |
| UNIQUE(`config_id`, `slug`) | |

### 2.3 `listings`
Stores the detailed listing data extracted from detail pages.

| Column | Type | Description |
|--------|------|-------------|
| `id` | `SERIAL` PRIMARY KEY | |
| `slug_id` | `INTEGER` REFERENCES `slugs(id)` | |
| `external_id` | `VARCHAR(100)` | Portal‑specific ID |
| `source_portal` | `VARCHAR(20)` | `otodom`, `gratka`, `morizon` |
| `source_url` | `TEXT` | |
| `title` | `TEXT` | |
| `description` | `TEXT` | |
| `city` | `VARCHAR(100)` | |
| `district` | `VARCHAR(100)` NULL | |
| `street` | `VARCHAR(200)` NULL | |
| `latitude` | `FLOAT` NULL | |
| `longitude` | `FLOAT` NULL | |
| `price_pln` | `INTEGER` NULL | |
| `price_per_m2` | `INTEGER` NULL | |
| `area_m2` | `FLOAT` NULL | |
| `rooms` | `INTEGER` NULL | |
| `floor` | `INTEGER` NULL | |
| `total_floors` | `INTEGER` NULL | |
| `year_built` | `INTEGER` NULL | |
| `has_lift` | `BOOLEAN` NULL | |
| `has_balcony` | `BOOLEAN` NULL | |
| `has_terrace` | `BOOLEAN` NULL | |
| `has_storage` | `BOOLEAN` NULL | |
| `heating_type` | `VARCHAR(50)` NULL | |
| `parking` | `VARCHAR(50)` NULL | |
| `building_material` | `VARCHAR(50)` NULL | |
| `property_type` | `VARCHAR(50)` NULL | |
| `market_type` | `VARCHAR(20)` NULL | |
| `listing_type` | `VARCHAR(20)` NULL | `agency` / `private` |
| `date_posted` | `TIMESTAMPTZ` NULL | |
| `date_scraped` | `TIMESTAMPTZ` DEFAULT NOW() | |
| `photo_count` | `INTEGER` DEFAULT 0 | |
| `has_floor_plan` | `BOOLEAN` DEFAULT FALSE | |
| `raw_json` | `JSONB` NULL | Full JSON payload for debugging |
| `created_at` | `TIMESTAMPTZ` DEFAULT NOW() | |
| `updated_at` | `TIMESTAMPTZ` DEFAULT NOW() | |

### 2.4 `price_history`
Append‑only record of price changes (per listing).

| Column | Type | Description |
|--------|------|-------------|
| `id` | `SERIAL` PRIMARY KEY | |
| `listing_id` | `INTEGER` REFERENCES `listings(id)` | |
| `price_pln` | `INTEGER` NOT NULL | |
| `price_per_m2` | `INTEGER` NULL | |
| `recorded_at` | `TIMESTAMPTZ` DEFAULT NOW() | |

### 2.5 `photos`
References to photo files stored in MinIO.

| Column | Type | Description |
|--------|------|-------------|
| `id` | `SERIAL` PRIMARY KEY | |
| `listing_id` | `INTEGER` REFERENCES `listings(id)` | |
| `minio_object_key` | `VARCHAR(500)` NOT NULL | Path within MinIO bucket |
| `original_url` | `TEXT` | |
| `position` | `INTEGER` | Order in gallery |
| `downloaded_at` | `TIMESTAMPTZ` DEFAULT NOW() | |

### 2.6 Indexes and Performance

To ensure efficient queries, the following indexes should be created:

- `slugs(config_id, slug)` – already unique, but also index for joins.
- `slugs(last_scraped_at, discovered_at)` – for daily slug selection.
- `slugs(is_active, last_seen_at)` – for detecting missing slugs.
- `listings(slug_id)` – foreign key index.
- `listings(date_scraped)` – for time‑based analytics.
- `price_history(listing_id, recorded_at)` – for price trend queries.
- `photos(listing_id, position)` – for gallery ordering.

All indexes are created via migration scripts and should be monitored for performance.

---

## 3. Storage Layer (PostgreSQL + MinIO)

### 3.1 PostgreSQL Client
- Use `psycopg` (sync) as required by project conventions.
- Create a `DatabaseClient` class that provides methods for:
  - Upserting search configurations.
  - Recording discovered slugs (insert new, update `last_seen_at`, mark missing slugs as inactive after 3 runs).
  - Inserting/updating listings (with detection of price changes → new `price_history` row).
  - Storing photo metadata.
- All DB methods are synchronous; no async/await.

### 3.2 MinIO Photo Manager
- Self‑hosted MinIO instance (S3‑compatible).
- `PhotoManager` class responsible for:
  - Downloading photo from original URL.
  - Generating a deterministic object key (e.g., `sha256(url + timestamp)`).
  - Uploading to MinIO bucket.
  - Returning the object key for database storage.
- Store actual photo binaries, never just URLs.

### 3.3 Integration with Scrapy Pipelines
Replace the stub pipelines with concrete implementations:

- `ValidationPipeline` (already exists) → keep as‑is.
- `PhotoDownloadPipeline` → uses `PhotoManager` to download and store photos, populates `photo_paths` in item.
- `DatabasePipeline` → uses `DatabaseClient` to persist listing, slug, price history, and photo metadata.

---

## 4. Separate Spiders

### 4.1 SlugCollectorSpider
- **Purpose**: Run once per day per search configuration. Collects all slugs from search pages (Phase 1 of current OtodomSpider).
- **Input**: `search_configuration_id` (or parameters directly).
- **Behavior**:
  1. Fetch search pages, extract slugs and investments.
  2. Expand investments into unit slugs (same logic as `_on_investment_page`).
  3. Record slugs in database via `DatabaseClient` (upsert, update `last_seen_at`).
  4. If `phase1_only` flag is set (default), stop after slug collection.
- **Output**: No scraped items; only DB updates.

### 4.2 DetailScraperSpider
- **Purpose**: Scrape **all** slugs every day, guaranteeing that slugs added today are visited today, and remaining slugs are visited once per day. Slugs are traversed in random order with random intervals to spread load and avoid detection.
- **Input**: `search_configuration_id` (optional; can work across all configurations).
- **Behavior**:
  1. At the start of each day, compute the set of slugs that have not been scraped today (`last_scraped_at` < today) or never scraped (`last_scraped_at` IS NULL). Prioritize slugs where `discovered_at` = today.
  2. Shuffle the list randomly to produce a random order.
  3. Iterate over the shuffled list, requesting each detail page with a random delay between requests (configurable, e.g., 10–30 seconds).
  4. For each slug, parse the detail page (same as `parse_detail`) and yield `RawListingItem`.
  5. Update `last_scraped_at` to now and increment `scrape_count`.
  6. If the spider cannot finish all slugs within 24 hours (e.g., due to rate limits), it will resume where it left off, ensuring no slug is skipped.
- **Output**: `RawListingItem` instances.
- **Performance considerations**: With hundreds of slugs, the spider will run continuously throughout the day. Anti‑detection settings (download delay, concurrent requests) must be adjusted accordingly.

### 4.3 Shared Components
- `SlugManager`: Encapsulates database queries for slug selection and status updates.
- `InvestmentExpander`: Reusable logic for handling investment pages (API + HTML fallback).
- `DetailParser`: Pure function that extracts fields from `__NEXT_DATA__` JSON.

These components can be injected into spiders via constructor arguments (dependency injection).

### 4.4 Error Handling and Resilience

To ensure robustness against network failures, rate limits, and website changes, the following measures are incorporated:

- **Retry with exponential backoff**: Both spiders retry failed requests (HTTP 429, 500, 502, 503, 504) with increasing delays, up to a configurable maximum attempts.
- **Circuit breakers**: If a portal consistently returns errors (e.g., 10 consecutive failures), the spider pauses requests to that portal for a cooling‑off period (e.g., 1 hour).
- **Fallback parsing**: If the primary JSON extraction fails, the detail spider attempts to extract key fields from HTML using CSS selectors (already implemented for investments).
- **Error logging and monitoring**: All errors are logged with structured context (spider name, URL, response status) and forwarded to the monitoring system for alerting.
- **Automatic recovery**: Spiders can resume from the last successful slug after a crash, thanks to the `last_scraped_at` tracking.

These mechanisms are implemented as Scrapy middlewares and integrated into the spider's request‑handling pipeline.

### 4.5 Scalability Considerations

The system is designed to handle up to several thousand slugs per day with a single spider instance. If the volume grows beyond that, the following scaling strategies can be applied:

- **Parallel spider instances**: Run multiple `DetailScraperSpider` instances, each assigned a distinct subset of slugs (sharding by `config_id` or hash of slug). Use a distributed lock (e.g., PostgreSQL advisory lock) to avoid duplicate scraping.
- **Dynamic delay adjustment**: Monitor error rates and response times; automatically increase delays when errors spike to avoid bans.
- **Horizontal scaling**: Deploy multiple scheduler containers behind a load balancer, each responsible for a subset of search configurations.
- **Database connection pooling**: Use `psycopg` connection pools to handle concurrent database queries from multiple spiders.
- **Caching**: Cache search page responses (HTTP cache) to reduce load on target sites and speed up slug collection.

The initial implementation assumes a single instance; scaling features can be added incrementally as needed.

### 4.6 Data Consistency and Concurrency Control

To ensure data integrity across concurrent spider instances and daily runs, the following measures are taken:

- **Foreign‑key constraints**: All relationships (slugs→config, listings→slugs, price_history→listings, photos→listings) are enforced at the database level.
- **Unique constraints**: The combination `(config_id, slug)` is unique; duplicate slugs cannot be inserted for the same configuration.
- **Transaction isolation**: Each database operation (e.g., updating a slug's `last_scraped_at` and inserting a new listing) is wrapped in a single transaction to guarantee atomicity.
- **Optimistic concurrency control**: When multiple spider instances might process the same slug (e.g., during scaling), the `last_scraped_at` timestamp is used as a version token: an update only succeeds if the slug hasn't been scraped since the spider fetched it.
- **Serializable isolation for slug selection**: The query that selects slugs for scraping uses `FOR UPDATE SKIP LOCKED` to prevent two spiders from picking the same slug while allowing high concurrency.

These techniques guarantee that each slug is scraped exactly once per day, listings are correctly linked, and price history is append‑only.

---

## 5. Scheduling System

Use **APScheduler** inside a long‑running Python process.

- One scheduler instance runs on the server.
- **Job 1**: Daily slug collection (e.g., 02:00). Launches `SlugCollectorSpider` via `subprocess.run()` (to avoid Twisted reactor conflicts).
- **Job 2**: Start the `DetailScraperSpider` daemon after slug collection completes (e.g., 02:30). The daemon runs until it has scraped all slugs that have not been scraped today, then exits. It prioritizes slugs added today, processes slugs in random order, and introduces random delays between requests to avoid detection.
- If the daemon fails or exits early, the scheduler restarts it after a configurable backoff.
- Jobs are configurable via a settings file (YAML/JSON).
- The scheduler can be managed via a lightweight HTTP API (FastAPI) for manual triggers and monitoring.

Alternatively, use **systemd timers** or **cron** for simplicity, but APScheduler provides more control and in‑process logging.

---

## 6. Dockerization

Create a multi‑container Docker Compose setup:

```yaml
version: '3.8'
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: listing_lens
      POSTGRES_USER: listing_lens
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD}
    volumes:
      - minio_data:/data
    ports:
      - "9000:9000"   # API
      - "9001:9001"   # Console

  scheduler:
    build: .
    command: poetry run python -m scheduler.run
    depends_on:
      - postgres
      - minio
    environment:
      DATABASE_URL: postgresql://listing_lens:${POSTGRES_PASSWORD}@postgres/listing_lens
      MINIO_ENDPOINT: minio:9000
      MINIO_ACCESS_KEY: ${MINIO_ROOT_USER}
      MINIO_SECRET_KEY: ${MINIO_ROOT_PASSWORD}
    volumes:
      - ./data:/app/data   # for spider run directories (optional)

  # Optional: monitoring dashboard (Grafana + Prometheus)
```

The `scheduler` container runs the APScheduler process and launches spiders in subprocesses.

---

## 7. Deployment on Cloud VM

1. **Provision a Linux VM** (Ubuntu 22.04) with Docker Engine installed.
2. **Clone repository** and set environment variables in `.env`.
3. **Run `docker‑compose up -d`** to start PostgreSQL, MinIO, and the scheduler.
4. **Set up reverse proxy** (nginx) if external access to MinIO console or monitoring is needed.
5. **Configure backups**:
   - PostgreSQL daily dump to object storage.
   - MinIO bucket replication (optional).
6. **Monitoring**:
   - Scrapy logs captured via `structlog` and shipped to Loki.
   - Metrics (scraped items, errors, response times) exposed via Prometheus and visualized in Grafana.
   - Health checks on scheduler HTTP endpoint.

---

## 8. Documentation and Monitoring Plan

### 8.1 Documentation
- **Architecture Decision Record (ADR)**: Document the chosen design (this document).
- **Runbook**: Step‑by‑step instructions for deployment, scaling, and troubleshooting.
- **API documentation**: For the scheduler’s HTTP API (if exposed).

### 8.2 Monitoring
- **Metrics collection**:
  - Scrapy logs captured via `structlog` in JSON format, shipped to Loki.
  - Application metrics (scraped items per hour, error rates, request latency) exposed via Prometheus.
  - Database metrics (query latency, connection count) via PostgreSQL exporter.
  - MinIO metrics (storage usage, request count) via MinIO’s Prometheus endpoint.
- **Dashboards** (Grafana):
  - **Scraping health**: Number of active slugs, scraping velocity, success/failure ratio.
  - **System health**: CPU, memory, disk usage of containers.
  - **Business metrics**: Total listings, new listings per day, price trends.
- **Health checks**:
  - HTTP endpoint `/health` on scheduler returning status of PostgreSQL, MinIO, and spider queue.
  - Synthetic transactions: periodic test scrapes to verify parsing still works.

### 8.3 Alerting
Configure alerts (via Alertmanager or similar) for:
- **Spider failures**: Non‑zero exit code from any spider run.
- **Error rate spikes**: >10% error rate on requests over a 15‑minute window.
- **Scraping stagnation**: No new listings scraped for 24 hours (configurable per portal).
- **Database connectivity**: Unable to connect to PostgreSQL for >5 minutes.
- **Storage capacity**: MinIO disk usage >85%.
- **Service downtime**: Scheduler health endpoint returns non‑200 for >5 minutes.

### 8.4 Log Retention and Analysis
- Retain logs for 30 days in Loki; archive older logs to cold storage.
- Use log queries to investigate scraping issues (e.g., filter by HTTP status 429).

---

## 9. Gaps and Considerations

The design above addresses the core requirements but leaves several important aspects unaccounted for. A robust production service should also consider:

### 9.1 Error Handling and Resilience
- **Retry logic**: Spiders should retry failed requests with exponential backoff, especially for HTTP 429/503.
- **Circuit breakers**: Temporarily stop scraping a portal if consecutive failures suggest a ban.
- **Fallback parsing**: If the primary JSON extraction fails, attempt HTML fallback (already present for investments).
- **Monitoring of failures**: Track error rates and alert on abnormal patterns.

### 9.2 Data Consistency and Performance
- **Database indexes**: Create indexes on `slugs(last_scraped_at, discovered_at)`, `slugs(config_id)`, `listings(slug_id)`.
- **Concurrency control**: Use database transactions for slug updates to avoid race conditions when multiple spider instances run.
- **Soft deletion**: Keep historical slugs even when inactive to maintain referential integrity.

### 9.3 Scalability
- **Parallel scraping**: If the number of slugs grows beyond a few thousand, consider sharding by configuration or using multiple detail spider instances (with distinct IPs).
- **Dynamic delay adjustment**: Increase delays during high error rates to reduce detection risk.
- **Load estimation**: Calculate maximum slugs per day given rate limits (e.g., 30‑second delay → ~2880 slugs/day). Ensure the spider can finish within 24 hours.

### 9.4 Configuration Management
- **Admin interface**: Provide a simple UI or CLI to add/update search configurations without editing code.
- **Configuration versioning**: Track changes to search parameters and their effective dates.

### 9.5 Photo Storage and Lifecycle
- **Duplicate detection**: Avoid storing the same photo multiple times across listings (hash‑based deduplication).
- **Storage cleanup**: Define a retention policy for old photos (e.g., keep for 2 years after listing removal).
- **Error recovery**: If a photo download fails, retry later and mark the listing as “photos pending”.

### 9.6 Legal and Ethical Compliance
- **Respect robots.txt**: Check and adhere to each portal’s robots.txt before scraping.
- **Crawl‑delay**: Honor any specified delay; adjust spider intervals accordingly.
- **Data privacy**: Ensure personal data (e.g., phone numbers) is not stored unless explicitly required; consider anonymization.

### 9.7 Monitoring and Alerting (Enhanced)
- **Real‑time dashboards**: Show number of active slugs, scraping velocity, error rates, and storage usage.
- **Anomaly detection**: Alert when scraped listings drop significantly compared to historical averages.
- **Health checks**: Endpoints for each service (PostgreSQL, MinIO, scheduler) to be monitored by external tools.

### 9.8 Testing and Maintenance
- **Unit and integration tests**: Cover spiders, database client, and photo manager.
- **Test containers**: Use PostgreSQL and MinIO test containers for CI.
- **Change detection**: Regularly run a smoke test that verifies the spider can still parse a sample page; alert on structural changes.

### 9.9 Deployment and Operations
- **Secrets management**: Use a dedicated secret store (Hashicorp Vault, AWS Secrets Manager) instead of environment files.
- **Backup strategy**: Automated daily backups of PostgreSQL and MinIO, with off‑site replication.
- **Disaster recovery**: Document recovery steps for database corruption or MinIO failure.

### 9.10 Cost Optimization
- **Resource sizing**: Right‑size VM and storage based on actual usage; scale down during low activity.
- **Caching**: Cache search page responses (HTTP cache) to reduce load on target sites and improve speed.

Addressing these gaps will require additional implementation effort but will result in a more reliable, maintainable, and scalable service.

---

## Next Steps

1. **Implement database schema** (SQL migration scripts).
2. **Build `DatabaseClient` and `PhotoManager`**.
3. **Refactor OtodomSpider** into `SlugCollectorSpider` and `DetailScraperSpider`.
4. **Integrate APScheduler** with subprocess launching.
5. **Write Dockerfile and docker‑compose.yml**.
6. **Test on a local VM** before deploying to production.

---

## Mermaid ER Diagram

```mermaid
erDiagram
    search_configurations ||--o{ slugs : defines
    search_configurations {
        integer id PK
        varchar city
        varchar voivodeship
        varchar powiat
        varchar gmina
        varchar property_type
        varchar[] districts
        integer price_min
        integer price_max
        float area_min
        float area_max
        integer rooms_min
        integer rooms_max
        integer max_pages
        timestamptz created_at
        timestamptz updated_at
    }

    slugs ||--o{ listings : "has details"
    slugs {
        integer id PK
        integer config_id FK
        varchar slug
        timestamptz discovered_at
        timestamptz last_seen_at
        boolean is_active
        timestamptz last_scraped_at
        integer scrape_count
    }

    listings ||--o{ price_history : "price changes"
    listings ||--o{ photos : "has photos"
    listings {
        integer id PK
        integer slug_id FK
        varchar external_id
        varchar source_portal
        text source_url
        text title
        text description
        varchar city
        varchar district
        varchar street
        float latitude
        float longitude
        integer price_pln
        integer price_per_m2
        float area_m2
        integer rooms
        integer floor
        integer total_floors
        integer year_built
        boolean has_lift
        boolean has_balcony
        boolean has_terrace
        boolean has_storage
        varchar heating_type
        varchar parking
        varchar building_material
        varchar property_type
        varchar market_type
        varchar listing_type
        timestamptz date_posted
        timestamptz date_scraped
        integer photo_count
        boolean has_floor_plan
        jsonb raw_json
        timestamptz created_at
        timestamptz updated_at
    }

    price_history {
        integer id PK
        integer listing_id FK
        integer price_pln
        integer price_per_m2
        timestamptz recorded_at
    }

    photos {
        integer id PK
        integer listing_id FK
        varchar minio_object_key
        text original_url
        integer position
        timestamptz downloaded_at
    }
```

---

## System Architecture Diagram

```mermaid
flowchart TB
    subgraph "External"
        O[Otodom Website]
        G[Gratka/Morizon]
    end

    subgraph "Scraping Layer"
        Scheduler[APScheduler]
        SlugSpider[SlugCollectorSpider]
        DetailSpider[DetailScraperSpider]
        Pipelines[Scrapy Pipelines]
    end

    subgraph "Storage Layer"
        DB[(PostgreSQL)]
        MinIO[(MinIO)]
    end

    subgraph "Monitoring"
        Prometheus[Prometheus]
        Loki[Loki]
        Grafana[Grafana]
    end

    Admin[Admin CLI/UI] --> Scheduler
    Scheduler --> SlugSpider
    Scheduler --> DetailSpider
    SlugSpider --> O
    DetailSpider --> O
    SlugSpider --> Pipelines
    DetailSpider --> Pipelines
    Pipelines --> DB
    Pipelines --> MinIO
    SlugSpider -.->|logs| Loki
    DetailSpider -.->|logs| Loki
    Pipelines -.->|metrics| Prometheus
    Prometheus --> Grafana
    Loki --> Grafana
```