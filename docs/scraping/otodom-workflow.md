# otodom workflow

The Otodom scraper is split into two spiders so slug discovery and detail scraping
can run on different schedules.

## Spider roles

- `otodom_slugs`: crawl search pages, collect slugs, expand investment units.
- `otodom_detail`: visit listing pages and emit structured listing items.

## Local commands

From the task runner:

```powershell
just scrape-otodom-slugs
just scrape-otodom-slugs-1
just chain-otodom
just chain-otodom-1
```

Direct CLI examples:

```powershell
cd scrapy_project
poetry run scrapy crawl otodom_slugs -a config_file=../config/otodom.developer.yaml -a max_pages=1
poetry run scrapy crawl otodom_detail -a slug=some-listing-slug
```

## Detail spider invocation modes

`otodom_detail` chooses mode by priority:

1. `-a slug=<single-slug>`
2. `-a slugs=slug1,slug2,...` or `-a slugs_file=<path>`
3. `-a slug_collection_file=<path to slug_collection.jsonl>`
4. DB queue mode when `use_db_slug_queue` is enabled and no slug input is given

## Output layout

Slug spider run directory:

- `data/otodom/<timestamp>_slugs/slug_collection.jsonl`
- `data/otodom/<timestamp>_slugs/slug_run_meta.jsonl`

Detail spider run directory:

- `data/otodom/<timestamp>_detail/output.jsonl`
- `data/otodom/<timestamp>_detail/raw_output.jsonl`
- `data/otodom/<timestamp>_detail/detail_runs.jsonl`

## DB queue handoff

Slug observations are written to `raw_slugs`. Operational queue rows are refreshed into
`slugs` through `storage.db.refresh_slug_queue(conn)`. In DB mode, `otodom_detail`
queries pending rows from `slugs`.

## Investment unit expansion

For investment listings, slug collection uses browser-side fetch interception to discover
the runtime GraphQL persisted query hash and fetch unit URLs from the same page session.
This avoids hardcoded hashes and avoids direct unauthenticated API calls.
