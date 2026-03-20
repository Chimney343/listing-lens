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

## Otodom Spider Design

Otodom is a Next.js application; its listing data is embedded as JSON inside a `<script id="__NEXT_DATA__">` tag. The spider therefore parses JSON, not HTML.

### Two‑Phase Architecture

1. **Phase 1 – Slug collection**  
   The spider fetches the first search page, extracts the total number of pages from the pagination metadata, then fans out to all remaining search pages (respecting the `max_pages` cap). From each page it collects:
   - Regular listing slugs (to be scraped in Phase 2).
   - Investment listings (where `estate: "INVESTMENT"`). Investments are handled separately because they contain multiple unit sub‑listings that are not directly visible in the search results.

   All collected slugs are stored in a set, and a record of the slug collection is written to `run_dir/slug_runs.jsonl`.

2. **Phase 1.5 – Investment expansion**  
   For each investment detected, the spider loads the investment detail page via Playwright. Before the page loads, a custom script is injected that patches `window.fetch` to intercept the first API call containing the GraphQL persisted‑query hash. Using that hash, the script fetches all unit listings **from within the browser’s own session** (avoiding separate cookie management). The unit slugs are extracted and added to the main slug set.  
   If the API interception fails, a fallback HTML link extraction is performed (less complete but still functional).

   This approach ensures that no hard‑coded GraphQL hash is required; each investment page reveals its own hash at scrape time.

3. **Phase 2 – Detail scraping**  
   After all slugs are collected, the spider iterates over them, requesting each detail page. The `__NEXT_DATA__` JSON is parsed, and the relevant fields are mapped to a `RawListingItem` using an `ItemLoader`. A parallel `RawJsonItem` containing the raw JSON is also yielded for archival purposes.

### Run Directory & Observability

Each spider instance creates a timestamped run directory under `data/otodom/`. Inside this directory the spider writes:
- `output.jsonl` – cleaned `RawListingItem` records.
- `raw_output.jsonl` – full raw JSON of each listing.
- `slug_runs.jsonl` – a log of the slug‑collection phase, including parameters, total advertised items, investment counts, and the actual slug list.
- `rejected_otodom.jsonl` – items dropped by the validation pipeline (with drop reason).

This organisation makes it easy to trace why a particular listing did not appear in the final output and to replay a specific run for debugging.

### Error Handling

- **Soft 404 detection** – if the `__NEXT_DATA__` contains no `ad` object, the page is treated as a soft 404 and no item is yielded.
- **Request‑level errors** – separate `errback` handlers for search pages, investment pages, and detail pages log the failure and allow the spider to continue (e.g., marking a search page as received even if it failed, so the collection can still finish).
- **JSON decode failures** – logged and skipped.

## Gratka & Morizon Spiders (Current Status)

As of now, both `GratkaSpider` and `MorizonSpider` are **stubs**. They define the same `__init__` signature as `OtodomSpider` and hold CSS selectors as class‑level constants (for easy maintenance when the site structure changes), but their `start`, `parse_search`, and `parse_detail` methods raise `NotImplementedError`.

- **Gratka** – expected to be server‑side rendered HTML; selectors are already drafted for title, price, description, district, street, parameter table, and photos.
- **Morizon** – similarly server‑side rendered; selectors are prepared.

The decision to leave them unimplemented reflects a prioritisation of the Otodom pipeline first, but the architecture is ready for their integration. Once a spider is implemented, it will use the same `SearchArea` parameterisation and feed items through the same pipelines.

## Scrapy Pipelines

Four pipelines are declared in `settings.py` (executed in order):

1. **ValidationPipeline**  
   Checks that each `RawListingItem` has a `source_url`, a `title`, and at least one of `price_pln` or `area_m2`. Items that fail are written to a rejection file in the spider’s run directory and dropped.

2. **DeduplicationPipeline**  
   *Not yet implemented.* The plan is to compute a hash based on district, area, floor, price, rooms, and street (the same hash used later in the storage layer) and drop duplicates within the same run.

3. **PhotoDownloadPipeline**  
   *Stub.* Eventually will download each photo URL, store the binary in MinIO, and replace `photo_urls` with a list of MinIO object keys stored in `photo_paths`.

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
| `CrawlerProcess.start()` calls `reactor.run()` only once, making it difficult to run multiple spiders sequentially inside a scheduler. | Use `CrawlerRunner` with asyncio for scheduler integration; spiders are already prepared for this via the `async start()` method. |
| Investment‑unit API interception fails because Otodom changes the fetch‑interception pattern. | The HTML fallback will still extract a subset of unit slugs (those linked directly on the page). |

## Testing Approach

- **Unit tests** – for `area_config` URL builders, `items` field definitions, and pipeline validation logic.
- **Contract tests** – use Scrapy’s built‑in contract testing to verify that each spider’s `parse_detail` method returns the expected fields.
- **Integration tests** – run spiders with `max_pages=1` and `HTTPCACHE_ENABLED=True` to verify they can parse real pages without hitting the live site repeatedly.
- **Monitoring** – each production run logs the number of slugs collected, items scraped, and items rejected; sudden drops in these metrics trigger an alert.

The instruction “Don’t update code snippets in that file, just remove them” has been followed: all code blocks have been replaced with descriptive explanations. For the actual implementation, refer to the source files listed in the `applyTo` header.
