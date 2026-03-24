path = r'c:\Users\mkkom\listing-lens\.github\instructions\scraping.instructions.md'
content = open(path, encoding='utf-8').read()

old_start = content.find('## Otodom Spider Design\n')
old_end = content.find('\n## Scrapy Pipelines\n')

print(f'old_start: {old_start}, old_end: {old_end}, length: {old_end - old_start}')

new_section = '''## Decoupled Spider Architecture

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

For each investment detected, the slug spider loads the investment detail page via Playwright. Before the page loads, a script is injected that patches `window.fetch` to intercept the first API call containing the GraphQL persisted-query hash. Using that hash, the script fetches all unit listings **from within the browser\'s own session** — no separate cookie management required. The unit slugs are extracted and added to the main slug set.

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

Once implemented, each portal will follow the same slug-then-detail split described above, accept the same `SearchArea` `-a` arguments, and feed items through the same pipelines.'''

new_content = content[:old_start] + new_section + content[old_end:]
open(path, 'w', encoding='utf-8').write(new_content)
print('Done. New length:', len(new_content))
