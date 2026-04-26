# listing-lens

Automated pipeline for collecting, storing, and tracking property listings in Poland,
with current focus on Otodom and a scheduler-first architecture for recurring runs.

Primary documentation now lives in `docs/`.

Start here:

- [Documentation index](docs/README.md)
- [Quickstart](docs/getting-started/quickstart.md)
- [Scheduler service](docs/operations/scheduler-service.md)
- [Database schema reference](docs/database/schema-reference.md)

## Repository highlights

- Scraping stack: Scrapy + Playwright integration + anti-bot hardening.
- Scheduler stack: APScheduler (`main.py`) with typed manifest config.
- Storage stack: PostgreSQL tables managed by Alembic and helpers in `storage/db.py`.

## Runtime commands

Common commands via task runner:

```powershell
just setup
just scrape-otodom-slugs-1
just chain-otodom-1
just scheduler-dry-run
```

Full command details are documented in `docs/`.
