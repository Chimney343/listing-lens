# Kraków Property Search Pipeline — Project Overview

## Deployment Target

| Component       | Spec                                      |
| --------------- | ----------------------------------------- |
| **Hardware**    | Raspberry Pi 5, 8 GB RAM                  |
| **Storage**     | 500 GB NVMe (PCIe gen 2)                  |
| **OS**          | Raspberry Pi OS (64-bit) / Ubuntu Server  |

### PostgreSQL tuning (postgresql.conf)

```
shared_buffers         = 2GB
effective_cache_size   = 6GB
work_mem               = 64MB
maintenance_work_mem   = 512MB
max_connections        = 20
wal_buffers            = 64MB
random_page_cost       = 1.1    # NVMe; sequential and random cost near-equal
effective_io_concurrency = 256  # NVMe handles deep queue depth well
```

Postgres data directory must be on the NVMe mount, not the SD card. Symlink
`/var/lib/postgresql` → `/mnt/nvme/postgresql` after install, before first
`initdb`.

---

## Architecture

```
┌───────────────────────────────────────────────────────────────┐
│                    SCHEDULER (APScheduler)                     │
│  Tiered: new listings=daily, active=2-3d, stale=weekly        │
│  BlockingScheduler in main.py; managed by systemd             │
└──────┬──────────────────────────────────────┬─────────────────┘
       │                                      │
       ▼                                      ▼
┌────────────────┐                  ┌─────────────────────┐
│ SCRAPY SPIDERS │                  │  FRESHNESS CHECKER  │
│ otodom.pl      │                  │  re-check & price   │
│ gratka.pl      │                  │  change detection   │
│ morizon.pl     │                  └──────────┬──────────┘
│                │                             │
│ Anti-bot:      │                             │
│ scrapy-        │                             │
│ impersonate    │                             │
│ + fake-ua      │                             │
│ + autothrottle │                             │
└───────┬────────┘                             │
        │                                      │
        │ INSERT (append-only)                 │
        ▼                                      │
┌───────────────────────────────────────────────────────────────┐
│                    raw_listings (Alembic-managed)              │
│  Append-only ingest table. Never updated or deleted.           │
│  Contains raw JSON blob alongside normalised fields.           │
│  Source of truth for reprocessing.                             │
└──────────────────────────┬────────────────────────────────────┘
                           │
                           │ ListingProcessor (reads unprocessed rows)
                           ▼
┌───────────────────────────────────────────────────────────────┐
│              DEDUPLICATION ENGINE (SHA-256 + fuzzy)            │
└──────────────────────────┬────────────────────────────────────┘
                           │
                           ▼
┌───────────────────────────────────────────────────────────────┐
│         STORAGE LAYER — application tables (Alembic-managed)   │
│  listings, price_history, slugs, scores, feedback, report_jobs │
│  Photos: NVMe filesystem via PhotoStorage interface            │
└──────────────────────────┬────────────────────────────────────┘
                           │
                           │ dbt reads; never writes to application tables
                           ▼
┌───────────────────────────────────────────────────────────────┐
│              DERIVED LAYER (dbt-managed, dbt schema)           │
│  listings_current, listings_candidates, price_trends,          │
│  feedback_summary — SELECT transformations only                │
└──────────────────────────┬────────────────────────────────────┘
                           │
                           ▼
┌───────────────────────────────────────────────────────────────┐
│               LLM SCORING (Instructor + Pydantic)              │
│  Text scoring: structured data + description → JSON scores     │
│  Vision scoring: deferred (architecture supports it)           │
└──────────────────────────┬────────────────────────────────────┘
                           │
                           ▼
┌───────────────────────────────────────────────────────────────┐
│                      FEEDBACK LOOP                             │
│  CLI: viewed / dismissed / applied + reasons                   │
│  Weight recalibration from patterns                            │
└──────────────────────────┬────────────────────────────────────┘
                           │
                           ▼
┌───────────────────────────────────────────────────────────────┐
│                     REPORT WORKER                              │
│  Separate systemd service; polls report_jobs table             │
│  Runs LLM scoring on filtered listing sets                     │
│  Writes completed report back to Postgres                      │
└──────────────────────────┬────────────────────────────────────┘
                           │
                           ▼
┌───────────────────────────────────────────────────────────────┐
│                     API LAYER (FastAPI)                        │
│  POST /reports → 202 + job_id                                  │
│  GET  /reports/{id} → status: pending/processing/complete      │
│  GET  /reports/{id}/result → assembled report                  │
│  Local: exposed via Cloudflare Tunnel (no port forwarding)     │
│  Production: migrate to VPS, API layer is stateless            │
└───────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer              | Technology                                 | Rationale                                                                          |
| ------------------ | ------------------------------------------ | ---------------------------------------------------------------------------------- |
| **Hardware**       | Raspberry Pi 5 (8 GB) + 500 GB NVMe        | Self-hosted; pipeline, DB, API and worker all on-device                            |
| **Scraping**       | Scrapy + scrapy-impersonate                | Full framework: pipelines, middleware, retry, throttle — all built-in              |
| **Anti-bot**       | scrapy-impersonate + scrapy-fake-useragent | TLS/JA3 fingerprint spoofing + UA rotation without leaving Scrapy                  |
| **Scheduling**     | APScheduler (BlockingScheduler)            | In-process cron; main.py blocks on scheduler.start(); systemd keeps it alive       |
| **Process mgmt**   | systemd                                    | Service supervision, auto-restart on failure, starts on boot                       |
| **Database**       | PostgreSQL (data dir on NVMe)              | pg_dump → restore migration path to any hosted Postgres; no adapter rewrite        |
| **Schema mgmt**    | Alembic (hand-written SQL migrations)      | Owns all DDL for application tables; no autogenerate against live DB               |
| **Derived layer**  | dbt                                        | SELECT-only transformations on top of application tables; never touches DDL        |
| **Photo storage**  | Filesystem on NVMe                         | Abstracted behind PhotoStorage interface (put/get); swap to S3 client at migration |
| **LLM scoring**    | Instructor + Pydantic v2                   | Provider-agnostic structured output; works across Claude/OpenAI/Gemini/Ollama      |
| **API**            | FastAPI                                    | Async job pattern; integrates with existing Pydantic models; stateless             |
| **Exposure**       | Cloudflare Tunnel (local phase)            | No port forwarding required; free tier; handles TLS; replace with VPS at scale     |
| **Config**         | pydantic-settings + .env                   | Type-safe config                                                                    |

---

## Schema Management: Alembic vs dbt

These two tools operate on disjoint sets of objects and must never overlap.

**Alembic** owns all DDL — `CREATE TABLE`, `ALTER TABLE`, `CREATE INDEX`,
triggers. It manages every table that the application writes to:
`slug_runs`, `slugs`, `raw_listings`, `listings`, `price_history`, `scores`
(TODO Stage 5), `feedback` (TODO Stage 6), `report_jobs` (TODO Stage 7).
All schema changes go through an Alembic migration revision. No ad-hoc
`ALTER TABLE` in production. Alembic migrations are committed to version
control; the production DB is never ahead of or behind the codebase's
migration history.

**dbt** owns derived objects only — views and materialised tables produced by
`SELECT` transformations over the application tables. dbt operates in a
dedicated `dbt` schema to keep the namespaces clean. On every dbt run, its
output objects are dropped and recreated. This is by design: dbt outputs
contain no source-of-truth data, only computed results. Application tables
(`public` schema) are read-only from dbt's perspective. dbt never issues
`INSERT`, `UPDATE`, `DELETE`, or any DDL against `public` schema objects.

The boundary is enforced by convention and by dbt's `sources:` configuration,
which declares the application tables as external inputs. If a proposed dbt
model would require writing to an application table, that is a signal the
logic belongs in `ListingProcessor` or the scoring pipeline, not in dbt.

### Application tables (Alembic-managed, `public` schema)

| Table | Purpose | Status |
|---|---|---|
| `slug_runs` | One row per slug-collection spider run | ✓ implemented |
| `slugs` | One row per discovered listing URL; scrape queue | ✓ implemented |
| `raw_listings` | Append-only ingest log; every scraped item lands here | ✓ implemented |
| `listings` | Deduplicated canonical records; one row per real-world listing | TODO Stage 2 |
| `price_history` | Append-only price observations per listing | TODO Stage 2 |
| `scores` | LLM sub-scores and composite scores per listing | TODO Stage 5 |
| `feedback` | User feedback events (viewed / dismissed / applied) | TODO Stage 6 |
| `report_jobs` | Async report job queue; polled by the worker service | TODO Stage 7 |

### Derived tables (dbt-managed, `dbt` schema)

| Model | Purpose |
|---|---|
| `listings_current` | Most recent active listing per canonical ID |
| `listings_candidates` | Active listings with scores, ready for surfacing |
| `price_trends` | Price change aggregates per listing |
| `feedback_summary` | Aggregated feedback signals per listing |

---

## Raw Listings Layer

`raw_listings` is the append-only ingest table. The Scrapy `DatabasePipeline`
writes every validated item here and nowhere else. This table is never updated
or deleted from — it is a permanent audit log of everything the spiders have
ever seen.

Each row stores all normalised fields extracted by the spider, including
`price_pln` / `price_per_m2`, `photo_urls`, and `http_status`. No raw JSON
blob is stored in the DB — the per-run `raw_output.jsonl` files on disk serve
as the low-level archival format.

The `processed_at` column is `NULL` for unprocessed rows. `ListingProcessor`
(TODO Stage 2) processes these rows: deduplicates, upserts into `listings`,
appends to `price_history` on price change, and stamps `processed_at`.

The scraper and the processor run on independent cadences. The scraper has no
knowledge of the canonical schema. This decoupling means a two-week scraper
bug does not permanently corrupt `listings` — the garbage rows in
`raw_listings` are identifiable by scrape timestamp and `listings` is rebuilt
by re-running `ListingProcessor` against the clean rows.

---

## Storage Design

PostgreSQL and photos both live on the NVMe. No object store is needed locally.

**Photos** are stored as files under a structured path that mirrors S3 key
conventions for zero-remapping migration:

```
/mnt/nvme/photos/{portal}/{external_id}/{filename}.jpg
```

The pipeline interacts with photos exclusively through a `PhotoStorage`
interface:

```python
class PhotoStorage(Protocol):
    def put(self, key: str, data: bytes) -> str: ...
    def get(self, key: str) -> bytes: ...
```

`FilesystemPhotoStorage` implements this against the NVMe mount.
`S3PhotoStorage` implements the same interface against any S3-compatible API.
Switching at migration requires changing one line of DI wiring, not touching
pipeline code.

**Migration path (DB):** `pg_dump -Fc listing_lens > backup.dump` on the Pi,
`pg_restore` on the target host. Connection string in `.env` changes; no code
changes.

**Migration path (photos):** `aws s3 sync /mnt/nvme/photos s3://bucket`.
Swap `FilesystemPhotoStorage` for `S3PhotoStorage` in DI config. Keys are
structurally identical between filesystem and S3; no remapping needed.

---

## Report Worker & Job Queue

On-demand report generation uses Postgres as a job queue. No Redis, no Celery.

```sql
CREATE TABLE report_jobs (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    status      text NOT NULL DEFAULT 'pending',  -- pending/processing/complete/failed
    criteria    jsonb NOT NULL,
    result      jsonb,
    error       text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
```

The report worker is a separate systemd service (`listing-lens-worker.service`)
that polls this table. It uses the same Instructor + Pydantic scoring machinery
as Stage 5 — a report is a user-triggered scoring run over a filtered listing
set with a richer output format.

LLM calls are never made inline in the API layer. The API accepts the job and
returns immediately (202). The frontend polls `GET /reports/{id}` for status.

---

## Process Management

All long-running processes are managed by systemd, not Docker. Docker adds no
value on a single self-hosted machine and complicates log access and debugging.

Three service units:

- `listing-lens-scraper.service` — APScheduler main process (scraping pipeline)
- `listing-lens-worker.service` — ListingProcessor + report worker (polls
  `raw_listings` and `report_jobs`)
- `listing-lens-api.service` — FastAPI process

All units set `Restart=on-failure`, `RestartSec=30`, `After=postgresql.service`,
and write to the system journal (`journalctl -u listing-lens-scraper -f`).

Docker is reconsidered only if the API layer migrates to a cloud host that
requires it.

---

## Deduplication Engine (TODO — Stage 2)

`ListingProcessor` applies two-pass deduplication before upserting into
`listings`:

1. **SHA-256 hash** — exact match on the canonical key fields:
   `district | area_m2 | floor | price_pln | rooms | street`, hex-truncated to
   16 chars. Guaranteed to catch re-scraped identical listings.

2. **Fuzzy match** — catches listings reposted with minor field changes
   (e.g. price edits, title rewording). Strategy TBD in Stage 2.

The dedup hash is stored on `listings` for diagnostics. Exact-duplicate rows
in `raw_listings` are silently skipped (not promoted). Fuzzy duplicates are
merged into the existing canonical record with a new `price_history` row if
the price changed.

---

## PII Filtering

The `PiiFilterPipeline` in `property_scraper/pipelines.py` redacts personally
identifiable information from free-text fields before any item reaches the
`DatabasePipeline`. It uses [Presidio](https://microsoft.github.io/presidio/)
backed by a spaCy NLP model.

- **Targets:** `title` and `description` only.
- **Preserved:** structured address fields (`street`, `city`, `district`) —
  these are part of the dedup hash and property identity.
- **Behaviour:** detected entities are replaced with their entity type label
  (e.g. `PHONE_NUMBER`, `PERSON`); original text is never stored.
- **Config:** controlled via Scrapy settings — `PII_ENABLED`, `PII_ENTITIES`,
  `PII_LANGUAGE`, `PII_NLP_MODEL`, `PII_SCORE_THRESHOLD`. Set
  `PII_ENABLED=False` to skip (development only).

---

## Scrapy / APScheduler Integration Risk

Scrapy has its own Twisted reactor. It cannot run inline inside an APScheduler
job without reactor conflict. Each scheduled scrape job must launch Scrapy as a
subprocess (`subprocess.run`) or via `CrawlerProcess` in a dedicated thread.
This is a known integration point — resolve it explicitly in Stage 4 before
writing any scheduler-to-spider wiring.

---

## Execution Order

1. **Stage 1** — Scrapy spiders + anti-bot settings ✓
2. **Stage 2** — `ListingProcessor`: dedup engine + `listings` / `price_history` writes — **TODO**
3. **Stage 3** — `PhotoStorage` abstraction + NVMe layout + dbt models setup — **TODO**
4. **Stage 4** — Re-check freshness strategy + APScheduler + `main.py` + systemd units — **TODO**
5. **Stage 5** — LLM scoring engine (`scores` table) + system prompt — **TODO**
6. **Stage 6** — Feedback loop CLI + weight recalibration — **TODO**
7. **Stage 7** — FastAPI layer + report worker + Cloudflare Tunnel setup — **TODO**
