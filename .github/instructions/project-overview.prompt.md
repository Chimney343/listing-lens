# Kraków Property Search Pipeline — Project Overview

## Identity and Scope

This is the reference document for the Kraków Property Search Pipeline — a Python-based system that periodically scrapes real estate listings from Polish property portals, deduplicates them, scores them via LLM, and surfaces recommendations with red flags and composite scores through a feedback-driven CLI.

---

## Architecture

```
┌───────────────────────────────────────────────────────────────┐
│                    SCHEDULER (APScheduler)                     │
│  Tiered: new listings=daily, active=2-3d, stale=weekly        │
└──────┬──────────────────────────────────────┬─────────────────┘
       │                                      │
       ▼                                      ▼
┌────────────────┐                  ┌─────────────────────┐
│ SCRAPY SPIDERS │  [BUILT]         │  FRESHNESS CHECKER  │
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
│               STORAGE LAYER  [OPEN DECISION]                   │
│  DB: listings, price_history, sources, feedback                │
│  Object store: listing photo binaries                          │
└──────────────────────────┬────────────────────────────────────┘
                           │
                           ▼
┌───────────────────────────────────────────────────────────────┐
│               LLM SCORING (Instructor + Pydantic v2)           │
│  Text scoring: structured data + description → JSON scores     │
│  Vision scoring: deferred (architecture must support it)       │
└──────────────────────────┬────────────────────────────────────┘
                           │
                           ▼
┌───────────────────────────────────────────────────────────────┐
│                      FEEDBACK LOOP                             │
│  CLI: viewed / dismissed / applied + reasons                   │
│  Weight recalibration from feedback patterns                   │
└───────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer             | Technology                                 | Status        | Rationale                                                                      |
| ----------------- | ------------------------------------------ | ------------- | ------------------------------------------------------------------------------ |
| **Scraping**      | Scrapy + scrapy-impersonate                | Locked/Built  | Full framework: pipelines, middleware, retry, throttle — all built-in           |
| **Anti-bot**      | scrapy-impersonate + scrapy-fake-useragent | Locked/Built  | TLS/JA3 fingerprint spoofing + UA rotation without leaving Scrapy               |
| **Scheduling**    | APScheduler                                | Locked        | In-process cron, lightweight                                                    |
| **LLM scoring**   | Instructor + Pydantic v2                   | Locked        | Provider-agnostic structured output; works across Claude/OpenAI/Gemini/Ollama  |
| **Config**        | pydantic-settings + .env                   | Locked        | Type-safe config                                                                |
| **Storage**       | TBD                                        | **Open**      | See storage decision protocol below                                             |

---

## Project State

**Completed:** Stage 1 — Scrapy spiders for otodom.pl, gratka.pl, morizon.pl with scrapy-impersonate, scrapy-fake-useragent, and autothrottle. Treat this layer as reference implementation. Issues may be flagged but rewrites are not proposed unless explicitly requested.

**Not yet built:** Stages 2 through 6.

---

## Storage Decision — Open

Storage backend (database + object store) has **not been decided**. Do not assume any specific technology in stage specs or trade-off analysis until a decision is made.

Relevant axes for narrowing the decision:
- Self-hosted vs managed (operational overhead tolerance)
- Expected data volume: listings count, photo volume, price history depth
- Budget ceiling (monthly)
- Whether external dashboard access or API access is needed
- Acceptable migration complexity if the choice needs to change later

Known candidates (not yet evaluated against final constraints):

**Option A: Self-hosted PostgreSQL + MinIO on Hetzner — ~€9/mo**
- Hetzner CX32: 4 vCPU, 8 GB RAM, 160 GB SSD
- No per-GB billing; 160 GB holds ~50,000 listing photo sets comfortably
- Requires managing backups, updates, and security yourself

**Option B: Supabase Pro — ~$25/mo + small VPS for scheduler**
- 8 GB PostgreSQL + 100 GB storage + 250 GB bandwidth, managed
- Dashboard and direct DB access included
- Stage 3 would use `supabase-py` SDK rather than `psycopg` + `minio`
- Total ~$30/mo with a €5 Hetzner CX22 for the scheduler process

**Option C: Supabase Free — $0/mo (MVP only)**
- 500 MB DB + 1 GB storage
- Viable only if photos are stored selectively (e.g. top-scored listings only)
- Intended as a temporary starting point; plan migration path before hitting limits

Decision is not made until explicitly confirmed. Stage 3 spec will be written for whichever option is selected.

---

## Stage Execution Order

| Stage | File                  | Status      | Description                                      |
| ----- | --------------------- | ----------- | ------------------------------------------------ |
| 1     | `01_SCRAPING.md`      | **Done**    | Scrapy spiders + anti-bot configuration          |
| 2     | `02_DEDUPLICATION.md` | Not started | SHA-256 + fuzzy dedup engine                     |
| 3     | `03_STORAGE.md`       | Blocked     | DB schema + photo storage (awaits storage decision) |
| 4     | `04_FRESHNESS.md`     | Not started | Re-check strategy + APScheduler integration      |
| 5     | `05_SCORING.md`       | Not started | LLM scoring engine + system prompt               |
| 6     | `06_FEEDBACK.md`      | Not started | Feedback loop + weight recalibration             |
