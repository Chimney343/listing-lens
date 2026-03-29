# storage/schema

Human-readable SQL reference files that mirror the DDL managed by Alembic and dbt.

**These files are documentation only** — they are not executed directly.  
The authoritative schema source is:
- `alembic/versions/` — for application tables (`public` schema)
- `dbt_project/` (future) — for derived views (`dbt` schema)

---

## alembic/

SQL reference files matching the Alembic migrations.
Numbered in creation order to respect FK dependencies.

| File | Table(s) | Written by |
|---|---|---|
| `00_triggers.sql` | `set_updated_at()` trigger function | – |
| `01_slug_runs.sql` | `slug_runs` | `OtodomSlugSpider.closed()` → `_write_slug_run_to_db()` |
| `02_slugs.sql` | `raw_slugs` (log) + `slugs` (queue) | `DatabasePipeline` / `refresh_slug_queue()` |
| `03_raw_listings.sql` | `raw_listings` | `DatabasePipeline` |
| `04_listings.sql` | `listings` | `ListingProcessor` (Stage 2) |
| `05_price_history.sql` | `price_history` | `ListingProcessor` (Stage 2) |

### slug data flow

```
OtodomSlugSpider
  → SlugCollectionItem  → DatabasePipeline  → raw_slugs   (append-only log)
  → SlugRunMetaItem     → _write_slug_run_to_db()  → slug_runs

storage.db.refresh_slug_queue(conn)   (call separately — idempotent)
  → raw_slugs (GROUP BY full_url)  →  slugs  (operational queue, ON CONFLICT UPSERT)

OtodomDetailSpider  ←  reads slugs WHERE scrape_status = 'pending'
```

## dbt/

Placeholder for dbt model SQL files (Stage 3+).

dbt operates in a dedicated `dbt` schema. It reads from application tables
(`public` schema) via `sources:` declarations and never writes DDL or DML
against the application tables.

Planned models:
- `listings_current` — most recent active listing per canonical ID
- `listings_candidates` — active listings with scores, ready for surfacing
- `price_trends` — price change aggregates per listing
- `feedback_summary` — aggregated feedback signals per listing
