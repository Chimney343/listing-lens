# listing-lens documentation

This folder is the canonical home for user-facing project documentation.

If you are new to the repository, start here:

- [Quickstart](getting-started/quickstart.md)
- [Environment variables](configuration/environment-variables.md)
- [Scheduler manifest](configuration/scheduler-manifest.md)
- [Otodom workflow](scraping/otodom-workflow.md)
- [Scheduler service](operations/scheduler-service.md)
- [Database schema reference](database/schema-reference.md)
- [Roadmap](roadmap.md)

## Current project status

Implemented now:

- Scrapy spiders for Otodom slug collection and detail scraping.
- Scheduler scaffold with typed manifest models and APScheduler registration.
- PostgreSQL storage helpers for `raw_listings`, `raw_slugs`, `slug_runs`, and queue refresh.
- Local process and service entrypoints via `just`, `main.py`, and systemd unit template.

Partially implemented or planned:

- Gratka and Morizon spiders are scaffolded, not complete.
- Canonical listing processing and dedup pipeline stages are still in progress.
- dbt derived models, LLM scoring, and feedback loop are planned stages.

## Scope boundary

Internal agent instruction files under `.github/instructions/` and `.github/copilot-instructions.md`
are intentionally outside this docs set.