# Kraków Property Search Pipeline — Project Overview

## Architecture

```
┌───────────────────────────────────────────────────────────────┐
│                    SCHEDULER (APScheduler)                     │
│  Tiered: new listings=daily, active=2-3d, stale=weekly        │
└──────┬──────────────────────────────────────┬─────────────────┘
       │                                      │
       ▼                                      ▼
┌────────────────┐                  ┌─────────────────────┐
│ SCRAPY SPIDERS │                  │  FRESHNESS CHECKER  │
│ otodom.pl      │                  │  re-check & price   │
│ gratka.pl      │                  │  change detection    │
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
│                    STORAGE LAYER (PostgreSQL + MinIO)            │
│  DB: listings, price_history, sources, feedback                │
│  Object store: actual photo binary files                       │
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
└───────────────────────────────────────────────────────────────┘
```

## Tech Stack

| Layer              | Technology                                | Rationale                                                                 |
| ------------------ | ----------------------------------------- | ------------------------------------------------------------------------- |
| **Scraping**       | Scrapy + scrapy-impersonate               | Full framework: pipelines, middleware, retry, throttle — all built-in      |
| **Anti-bot**       | scrapy-impersonate + scrapy-fake-useragent| TLS/JA3 fingerprint spoofing + UA rotation without leaving Scrapy          |
| **Scheduling**     | APScheduler                               | In-process cron, lightweight                                               |
| **Database**       | Hetzner VPS + PostgreSQL + MinIO         | Self-hosted: 160 GB disk, no storage caps, ~€9/mo all-in                  |
| **Photo storage**  | MinIO (S3-compatible, self-hosted)        | Store actual photo files, not URLs; unlimited by disk size                 |
| **LLM scoring**    | Instructor + Pydantic v2                  | Provider-agnostic structured output; works across Claude/OpenAI/Gemini/Ollama |
| **Config**         | pydantic-settings + .env                  | Type-safe config                                                           |

## Storage Options (Detailed)

The 500 MB free tier on both Supabase and Neon is too small once you're storing photos. Here are the realistic options:

### Option A: Self-hosted PostgreSQL + MinIO — ~€9/mo (Recommended)
- **Hetzner CX32**: €8.50/mo (4 vCPU, 8 GB RAM, 160 GB SSD)
- Run PostgreSQL + MinIO (S3-compatible object storage) on same VPS
- 160 GB holds ~50,000 listing photo sets comfortably. No per-GB billing.
- **Stage 3 doc is written for this option.**
- **Downside**: You manage backups, updates, security

### Option B: Supabase Pro — $25/mo (Managed Alternative)
- **DB**: 8 GB PostgreSQL — holds tens of thousands of listings with full history
- **Storage**: 100 GB Supabase Storage — holds ~50,000+ listing photo sets
- **Bandwidth**: 250 GB/mo
- **Why**: Managed PostgreSQL + S3-compatible storage in one platform, dashboard included
- **Total with VPS**: ~$30/mo ($25 Supabase + €5 Hetzner CX22 for scheduler)
- **Requires adapting Stage 3** to use `supabase-py` SDK instead of `psycopg` + `minio`

### Option C: Supabase Free + selective photos — $0/mo (MVP only)
- 500 MB DB + 1 GB storage
- Store photos only for top-scored listings (composite_score > 3.5)
- Keep photo URLs for everything else
- **Migrate to Option A or B when free tier gets tight**

## Execution Order

1. **Stage 1** — `01_SCRAPING.md` — Scrapy spiders + anti-bot settings
2. **Stage 2** — `02_DEDUPLICATION.md` — Hash + fuzzy dedup engine
3. **Stage 3** — `03_STORAGE.md` — DB schema + photo storage
4. **Stage 4** — `04_FRESHNESS.md` — Re-check strategy + APScheduler
5. **Stage 5** — `05_SCORING.md` — LLM scoring engine + system prompt
6. **Stage 6** — `06_FEEDBACK.md` — Feedback loop + weight recalibration
