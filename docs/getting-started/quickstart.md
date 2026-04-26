# quickstart

This quickstart gets you from clone to a basic local Otodom scrape.

## Prerequisites

- Python 3.11+
- Poetry
- PostgreSQL reachable from your `DATABASE_URL`
- Playwright Chromium (used by scraping)

## 1. Install dependencies and local templates

Use the task runner:

```powershell
just setup
```

This installs Python dependencies, installs Chromium for Playwright, and creates
local `.env` and `config/spider_jobs.yaml` if they are missing.

If you prefer manual setup:

```powershell
poetry install
poetry run playwright install chromium
Copy-Item .env.example .env
Copy-Item config/spider_jobs.example.yaml config/spider_jobs.yaml
```

## 2. Verify configuration

Update values in `.env` for your machine, especially `DATABASE_URL`.

Reference:

- [Environment variables](../configuration/environment-variables.md)

## 3. Run a one-page slug collection smoke test

```powershell
just scrape-otodom-slugs-1
```

This executes `otodom_slugs` with a conservative profile and a one-page cap.

## 4. Run the chained local flow

```powershell
just chain-otodom-1
```

This runs `otodom_slugs` and then `otodom_detail` for locally collected slugs.

## 5. Validate scheduler wiring

```powershell
just scheduler-dry-run
```

This validates and registers jobs from `config/spider_jobs.yaml` without starting
the long-running scheduler loop.

## Where outputs appear

- Slug run artifacts: `data/otodom/<timestamp>_slugs/`
- Detail run artifacts: `data/otodom/<timestamp>_detail/`
- Application logs: `logs/`

For scheduler deployment and service mode, see:

- [Scheduler service](../operations/scheduler-service.md)
