# database schema reference

This document summarizes the current application schema and slug queue flow.

Authoritative DDL source:

- `alembic/versions/0001_initial_schema.py`
- `alembic/versions/0002_split_slugs.py`

Data mapping helpers:

- `storage/db.py`

## Table overview

| Table | Purpose | Primary writer |
|---|---|---|
| `slug_runs` | One row per slug spider run | Otodom slug spider close hook |
| `raw_slugs` | Append-only slug observation log | `DatabasePipeline` |
| `slugs` | Operational deduplicated slug queue | `refresh_slug_queue()` |
| `raw_listings` | Append-only listing ingest table | `DatabasePipeline` |
| `listings` | Canonical deduplicated listings | Listing processor stage (planned) |
| `price_history` | Append-only prices over time | Listing processor stage (planned) |
| `feedback` | User feedback events | Feedback stage (planned) |
| `report_jobs` | Async report job queue | API and worker stages (planned) |

## Slug data flow

1. `otodom_slugs` yields `SlugCollectionItem` records.
2. Pipeline writes each observation into `raw_slugs`.
3. `storage.db.refresh_slug_queue(conn)` aggregates observations into `slugs`.
4. `otodom_detail` DB mode reads pending rows from `slugs`.

Queue refresh is idempotent and re-queues previously scraped slugs when a newer
observation is seen after the last scrape.

## Migration notes

- Revision `0001` creates the initial schema and update triggers.
- Revision `0002` splits legacy `slugs` into `raw_slugs` and new operational `slugs`.

## Derived layer note

dbt-derived models are planned and are not yet implemented in this repository.
