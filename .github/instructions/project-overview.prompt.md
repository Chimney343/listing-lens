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
        ▼                                      ▼
┌───────────────────────────────────────────────────────────────┐
│              DEDUPLICATION ENGINE (SHA-256 + fuzzy)            │
└──────────────────────────┬────────────────────────────────────┘
                           │
                           ▼
┌───────────────────────────────────────────────────────────────┐
│              STORAGE LAYER (PostgreSQL + filesystem)           │
│  DB: listings, price_history, sources, feedback, report_jobs  │
│  Photos: NVMe filesystem via PhotoStorage interface            │
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
| **Photo storage**  | Filesystem on NVMe                         | Abstracted behind PhotoStorage interface (put/get); swap to S3 client at migration |
| **LLM scoring**    | Instructor + Pydantic v2                   | Provider-agnostic structured output; works across Claude/OpenAI/Gemini/Ollama      |
| **API**            | FastAPI                                    | Async job pattern; integrates with existing Pydantic models; stateless             |
| **Exposure**       | Cloudflare Tunnel (local phase)            | No port forwarding required; free tier; handles TLS; replace with VPS at scale     |
| **Config**         | pydantic-settings + .env                   | Type-safe config                                                                    |

---

## Storage Design

PostgreSQL and photos both live on the NVMe. No object store is needed locally.

**Photos** are stored as files under a structured path that mirrors what an S3
key would look like at migration time:

```
# TODO: confirm whether key includes 'listings/' prefix or starts directly with {portal}/
# Option A: /mnt/nvme/photos/listings/{portal}/{external_id}/{filename}.jpg
# Option B: /mnt/nvme/photos/{portal}/{external_id}/{filename}.jpg
```

Align this with `storage.instructions.md` once decided.

The pipeline interacts with photos exclusively through a `PhotoStorage`
interface:

```python
class PhotoStorage(Protocol):
    def put(self, key: str, data: bytes) -> str: ...
    def get(self, key: str) -> bytes: ...
```

`LocalPhotoStorage` implements this against the filesystem. `S3PhotoStorage`
implements the same interface against any S3-compatible API. Switching at
migration requires changing one line of DI wiring, not touching pipeline code.

**Migration path (DB):** `pg_dump -Fc listing_lens > backup.dump` on the Pi,
`pg_restore` on the target host. Connection string in `.env` changes; no code
changes.

**Migration path (photos):** `aws s3 sync /mnt/nvme/photos s3://bucket` (or
equivalent). Swap `LocalPhotoStorage` for `S3PhotoStorage` in DI config.

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

Two service units:

- `listing-lens.service` — APScheduler main process (scraping pipeline)
- `listing-lens-worker.service` — Report worker (polls report_jobs)

Both units set `Restart=on-failure`, `RestartSec=30`, `After=postgresql.service`,
and write to the system journal (`journalctl -u listing-lens -f`).

Docker is reconsidered only if the API layer migrates to a cloud host that
requires it.

---

## Scrapy / APScheduler Integration Risk

Scrapy has its own Twisted reactor. It cannot run inline inside an APScheduler
job without reactor conflict. Each scheduled scrape job must launch Scrapy as a
subprocess (`subprocess.run`) or via `CrawlerProcess` in a dedicated thread.
This is a known integration point — resolve it explicitly in Stage 4 before
writing any scheduler-to-spider wiring.

---

## Execution Order

1. **Stage 1** — `01_SCRAPING.md` — Scrapy spiders + anti-bot settings ✓
2. **Stage 2** — `02_DEDUPLICATION.md` — Hash + fuzzy dedup engine
3. **Stage 3** — `03_STORAGE.md` — DB schema + PhotoStorage abstraction + NVMe layout
4. **Stage 4** — `04_FRESHNESS.md` — Re-check strategy + APScheduler + Scrapy integration
5. **Stage 5** — `05_SCORING.md` — LLM scoring engine + system prompt
6. **Stage 6** — `06_FEEDBACK.md` — Feedback loop + weight recalibration
7. **Stage 7** — `07_API.md` — FastAPI layer + report_jobs table + worker service + Cloudflare Tunnel setup
