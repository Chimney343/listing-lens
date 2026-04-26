# roadmap

Status snapshot as of 2026-04-26.

## stage 1: scraping

In place:

- Otodom slug spider (`otodom_slugs`)
- Otodom detail spider (`otodom_detail`)
- Playwright-based anti-bot runtime setup and run-directory outputs

Partial:

- Gratka and Morizon spiders are scaffolded but not complete.

## stage 2: canonical listing processing

Planned:

- Deduplication into canonical `listings`
- Append-only updates to `price_history`
- Processing lifecycle from `raw_listings`

## stage 3: derived analytics layer

Planned:

- dbt-based derived models such as current listings and trends.

## stage 4: scheduler and operations

In place:

- Typed scheduler manifest and trigger registration
- APScheduler entrypoint in `main.py`
- systemd unit template for long-running scheduler process

## stage 5: llm scoring

Planned:

- Structured scoring outputs for listings.

## stage 6: feedback loop

Planned:

- Feedback event capture and downstream weighting signals.

## stage 7: report jobs and api

Partially planned:

- `report_jobs` table exists in schema.
- API and worker orchestration are not fully implemented.
