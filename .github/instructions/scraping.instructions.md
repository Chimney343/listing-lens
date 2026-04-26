---
applyTo: "**/spiders/**,**/scrapy_project/**,**/area_config*,**/items.py,**/pipelines.py,**/middlewares.py"
---

# Stage 1 — Scraping Layer (Scrapy)

## Objective

Build a Scrapy project with spiders for otodom.pl, gratka.pl, and morizon.pl that produce a standardized `RawListingItem`. The system is designed to be:

- **Stealthy**: Uses advanced anti‑detection techniques (TLS fingerprint spoofing, realistic browser profiles, randomised delays) to avoid being blocked.
- **Parameterised**: Every search dimension (city, districts, price range, area, rooms, max pages) is controlled via spider arguments, never hard‑coded.
- **Resilient**: Handles missing data, soft‑404 pages, and transient network errors without crashing.
- **Observable**: Each spider run creates a dedicated directory with timestamped logs, slug collection records, and raw JSON dumps for later debugging.
- **Extensible**: The pipeline architecture allows new portals to be added by implementing a new spider class and, if needed, adding portal‑specific URL builders.

The ultimate goal is to feed clean, deduplicated listing data into the downstream storage and scoring stages of the property pipeline.

## Dependencies

The scraping layer relies on the following key packages:

- **scrapy** (≥2.14) – core crawling framework.
- **scrapy‑impersonate** (≥1.6) – TLS/JA3 fingerprint spoofing via `curl_cffi`. Used to mimic real browser TLS signatures.
- **scrapy‑fake‑useragent** (≥1.3) – rotates User‑Agent strings based on real‑world browser statistics.
- **scrapy‑playwright** (≥0.0.41) – fallback for JavaScript‑rendered content and for interacting with pages that require a browser session (e.g., Otodom investment units).
- **Pillow** (≥10.4) – image processing (future photo pipeline).
- **pydantic** (≥2.9) – validation of configuration and data models.

All dependencies are managed by Poetry; the `pyproject.toml` is the single source of truth. Development dependencies (pytest, black, etc.) are kept in the `dev` group.

## Scrapy Anti‑Bot Configuration (Design Decisions)

The `settings.py` file is hardened to maximise stealth while maintaining reasonable throughput. Key design choices:

- **Asyncio reactor** – required by `scrapy‑impersonate` and `scrapy‑playwright`.
- **Download handlers** – configured to use Playwright for all HTTP/HTTPS requests, giving each request a real browser context with realistic headers, viewport, locale (pl‑PL), and timezone (Europe/Warsaw). This defeats many client‑side fingerprinting checks.
- **Request throttling** – `AUTOTHROTTLE_ENABLED` with a start delay of 3 s and a max delay of 15 s, plus a fixed `DOWNLOAD_DELAY` of 12 s (randomised ±50%). These values were chosen to mimic a cautious human browsing pattern.
- **Concurrency** – limited to 8 concurrent requests overall, but only 1 per domain to avoid overwhelming a single portal.
- **Retry logic** – retries on 403, 429, 5xx errors up to 3 times.
- **Resource blocking** – Playwright aborts requests for images, fonts, media, ping and WebSocket connections, cutting ~35k unnecessary sub‑requests per full run and reducing memory pressure.
- **Robots.txt** – deliberately ignored (`ROBOTSTXT_OBEY = False`) because all three portals block scrapers via their robots.txt; obeying it would stop the crawl completely.

The configuration is kept in a single file to make it easy to adjust when a portal changes its detection patterns.

## Parameterized Search Areas

Search criteria are never hard‑coded. Instead, every spider accepts a common set of `-a` arguments (city, districts, price_min, price_max, max_pages, etc.). These are parsed into a `SearchArea` dataclass defined in `area_config.py`.

- **SearchArea** – holds all filter parameters; defaults are set to a safe location (Mielec, podkarpackie) to prevent accidental large‑scale crawls of production data during development.
- **URL builders** – three functions (`build_otodom_url`, `build_gratka_url`, `build_morizon_url`) construct the appropriate search URL for each portal, incorporating the filters. The builders are kept separate from the spiders so that URL‑format changes can be applied in one place.
- **District mapping** – Otodom uses internal slugs for districts; a dictionary `OTODOM_DISTRICT_SLUGS` maps human‑readable district names to those slugs (currently only Kraków districts are listed, but the mapping can be extended).

The design ensures that the same search can be run across multiple portals with identical filters, making cross‑portal comparisons possible.

## Decoupled Spider Architecture

Each portal has **two spider classes**, not one:

| Class | Spider name | Responsibility |
|---|---|---|
| `OtodomSlugSpider` | `otodom_slugs` | Crawls search pages, expands investments, persists slug list |
| `OtodomDetailSpider` | `otodom_detail` | Visits individual advert URLs, yields `RawListingItem` |
| `GratkaSlugSpider` | `gratka_slugs` | Slug-collection role for Gratka |
| `GratkaDetailSpider` | `gratka_detail` | Detail scraping for Gratka |
| `MorizonSlugSpider` | `morizon_slugs` | Slug-collection role for Morizon |
| `MorizonDetailSpider` | `morizon_detail` | Detail scraping for Morizon |

### Why decouple?

In production, slug collection and detail scraping run on different schedules. Slug spiders can run frequently (detecting new listings and marking gone ones) without re-scraping every advert page. Detail spiders are only triggered when a slug has not yet been scraped or needs a refresh. Keeping them as separate Scrapy spiders lets the scheduler launch them independently and allows each one to be throttled, retried, and monitored separately.

### Slug spider (`*SlugSpider`)

Accepts the standard `SearchArea` `-a` arguments (`city`, `districts`, `price_min`, `price_max`, `max_pages`, etc.). Its only job is:

1. Fan out across all search result pages (respecting `max_pages`).
2. Collect every slug found — including investment parent slugs.
3. For **Otodom only**: expand each investment listing into its individual unit slugs (see "Otodom Investment Expansion" below).
4. Persist the collected slug list to `run_dir/slug_runs.jsonl` and — once the DB pipeline exists — upsert slugs into the database `slugs` table.
5. Yield **no `RawListingItem`s** — slug spiders do not visit advert pages.

### Detail spider (`*DetailSpider`)

Accepts a list of slugs to scrape. There are two invocation modes and **no third spider is needed** to bridge them — both modes are handled by the same `DetailSpider` class via its `start()` method:

- **Inline mode** (`-a slugs=slug1,slug2,...`): slugs are passed directly as a comma-separated spider argument. Used when the slug spider or the scheduler passes slugs explicitly, and during local development.
- **Database mode** (default when no `slugs` argument is given): the spider queries the database for all slugs whose `last_scraped_at` is older than a configurable threshold (or NULL), then issues one request per slug. This is the production path — the scheduler launches detail spiders that self-populate from the DB.

The detail spider visits each slug URL, parses the advert, and yields a `RawListingItem`. It also handles soft-404 detection as described below, and writes `rejected_*.jsonl` for items dropped by the validation pipeline.

> **Why not a third coordinator spider?** A coordinator spider would need to issue requests that trigger another spider, which is not a native Scrapy concept and requires external coordination via `CrawlerRunner`. Reading pending slugs directly from the DB inside `start()` achieves the same result within a single, well-understood Scrapy process. The DB is the natural hand-off point between the two spiders.

## Otodom Spider Details

Otodom is a Next.js application; its listing data is embedded as JSON inside a `<script id="__NEXT_DATA__">` tag. Both Otodom spiders parse JSON, not HTML.

### OtodomSlugSpider — Search Collection

The slug spider fetches the first search page, reads the total page count from the pagination metadata, then fans out to all remaining pages. From each page it separates:
- **Regular slugs** — added directly to the slug set.
- **Investment listings** (`estate: "INVESTMENT"`) — collected into a separate investment map with the ad ID, parent slug, and expected unit count. Processed in the investment expansion step below.

All collected slugs and the investment map are written to `run_dir/slug_runs.jsonl`.

### Otodom Investment Expansion

For each investment detected, the slug spider loads the investment detail page via Playwright. Before the page loads, a script is injected that patches `window.fetch` to intercept the first API call containing the GraphQL persisted-query hash. Using that hash, the script fetches all unit listings **from within the browser's own session** — no separate cookie management required. The unit slugs are extracted and added to the main slug set.

If the API interception fails, a fallback HTML link extraction is performed (less complete but still functional).

This approach ensures that no hard-coded GraphQL hash is required; each investment page reveals its own hash at scrape time.

### OtodomDetailSpider

Visits each slug at `https://www.otodom.pl/pl/oferta/{slug}`. Parses `__NEXT_DATA__` JSON, maps fields to a `RawListingItem` via `ItemLoader`, and yields a parallel `RawJsonItem` for archival purposes.

Error handling:
- **Soft 404** — if `__NEXT_DATA__` contains no `ad` object, the page is silently skipped.
- **Request errors** — `errback` logs the failure; the spider continues with remaining slugs.
- **JSON decode failures** — logged and skipped.

### Run Directory & Observability

Each spider instance creates a timestamped run directory under `data/otodom/`. The slug spider writes:
- `slug_runs.jsonl` — parameters, total advertised count, investment breakdown, and the full slug list.

The detail spider writes:
- `output.jsonl` — cleaned `RawListingItem` records.
- `raw_output.jsonl` — full raw JSON of each listing.
- `rejected_otodom.jsonl` — items dropped by the validation pipeline (with drop reason).

## Gratka & Morizon Spiders (Current Status)

Both portals currently have **stubs** for their slug and detail spiders. CSS selectors are defined as class-level constants (for easy maintenance when site structure changes), but `start()`, `parse_search()`, and `parse_detail()` raise `NotImplementedError`.

- **Gratka** — server-side rendered HTML. Selectors for title, price, description, district, street, parameter table, and photos are drafted and ready.
- **Morizon** — similarly server-side rendered. Selectors prepared.

Once implemented, each portal will follow the same slug-then-detail split described above, accept the same `SearchArea` `-a` arguments, and feed items through the same pipelines.

## Scrapy Pipelines

Four pipelines are declared in `settings.py` (executed in order):

1. **ValidationPipeline**  
   Checks that each `RawListingItem` has a `source_url`, a `title`, and at least one of `price_pln` or `area_m2`. Items that fail are written to a rejection file in the spider’s run directory and dropped.

2. **DeduplicationPipeline**  
   *Not yet implemented.* The plan is to compute a hash based on district, area, floor, price, rooms, and street (the same hash used later in the storage layer) and drop duplicates within the same run.

3. **PhotoDownloadPipeline**  
   *Stub.* Eventually will download each photo URL, store the binary via `PhotoStorage.put()`, and replace `photo_urls` with a list of storage keys in `photo_paths`.

4. **DatabasePipeline**  
   *Stub.* Will insert the validated, deduplicated listing into PostgreSQL (synchronous `psycopg` connection).

The pipeline order ensures that invalid items are filtered out before expensive I/O operations (photo download, DB insert).

## Soft 404 Detection

Each portal signals a removed/expired listing differently:

- **Otodom** – `ad` is `null` in the `__NEXT_DATA__` JSON.
- **Gratka** – page contains the text “Oferta nieaktualna”.
- **Morizon** – page contains the text “Ogłoszenie wygasło”.

Spiders check for these markers and skip yielding an item when detected. This prevents polluting the database with stale listings.

## Known Risks

| Risk | Mitigation |
|------|------------|
| Otodom changes the `__NEXT_DATA__` structure or migrates to React Server Components (RSC) flight data. | Monitor for zero‑item runs; consider adding `njsparser` as a fallback for RSC parsing. |
| `scrapy‑impersonate` TLS profiles become stale (portals start rejecting them). | Keep the library updated; fall back to `scrapy‑playwright` for all requests. |
| Gratka/Morizon change their HTML selectors. | Selectors are defined as class‑level constants; a single update in the spider file will fix all parsing. |
| `CrawlerProcess.start()` calls `reactor.run()` only once, making it difficult to run multiple spiders sequentially inside a scheduler. | Spiders are launched via `subprocess.run()` from APScheduler jobs to avoid Twisted reactor conflicts. Never call `CrawlerProcess` or `CrawlerRunner` inside a scheduler job. |
| Investment‑unit API interception fails because Otodom changes the fetch‑interception pattern. | The HTML fallback will still extract a subset of unit slugs (those linked directly on the page). |

## Slug Lifecycle

| Stage | Owner | What happens |
|---|---|---|
| Discovery | `OtodomSlugSpider._make_slug_item` | Yields `SlugCollectionItem` (UUID, `run_id`, `observed_at`). In-memory `self._slugs` set deduplicates within the run. |
| Raw log insert | `DatabasePipeline._process_slug_item` | Inserts one row into `raw_slugs` per observation. No UNIQUE constraint — the same slug across two runs = two rows. Insert errors are warnings, not fatal. |
| Queue refresh | `storage.db.refresh_slug_queue(conn)` | Idempotent `INSERT … ON CONFLICT` that aggregates `raw_slugs` → `slugs` (one row per `full_url`). Re-queues `'scraped'` slugs to `'pending'` when `last_seen_at > last_scraped_at`. Called by the coordinator, never by the spider. |
| Detail scrape | `OtodomDetailSpider` (DB mode, TODO) | Queries `slugs WHERE scrape_status = 'pending'`, scrapes, yields `RawListingItem`, marks slug `'scraped'`. |

```
OtodomSlugSpider → raw_slugs (append-only log)
                       ↓  refresh_slug_queue()  [separate call]
                   slugs (operational queue, scrape_status)
                       ↓
               OtodomDetailSpider
```

---

## Listing Lifecycle

TODO

---

## Testing Approach

- **Unit tests** – for `area_config` URL builders, `items` field definitions, and pipeline validation logic.
- **Contract tests** – use Scrapy’s built‑in contract testing to verify that each spider’s `parse_detail` method returns the expected fields.
- **Integration tests** – run spiders with `max_pages=1` and `HTTPCACHE_ENABLED=True` to verify they can parse real pages without hitting the live site repeatedly.
- **Monitoring** – each production run logs the number of slugs collected, items scraped, and items rejected; sudden drops in these metrics trigger an alert.

The instruction “Don’t update code snippets in that file, just remove them” has been followed: all code blocks have been replaced with descriptive explanations. For the actual implementation, refer to the source files listed in the `applyTo` header.
