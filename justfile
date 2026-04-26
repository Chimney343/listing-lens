# listing-lens task runner
# Run with: just <recipe>
# All Python/Scrapy commands execute via Poetry.

set shell := ["powershell", "-Command"]

# Make root-level modules (e.g. otodom_config) importable when scrapy runs from scrapy_project/.
export PYTHONPATH := justfile_directory()

# Install dependencies, install Playwright Chromium, and create missing local config files.
setup: _setup-deps _setup-browser setup-env-example setup-env scheduler-init-manifest

# Internal helper: install Python dependencies from pyproject.toml/poetry.lock.
_setup-deps:
    poetry install

# Internal helper: ensure Chromium is installed for scrapy-playwright spiders.
_setup-browser:
    poetry run playwright install chromium

# Create a documented .env.example template if missing.
setup-env-example:
    @if (Test-Path .env.example) { Write-Host ".env.example already exists." -ForegroundColor Yellow } else { "# listing-lens configuration template`n# Copy this file to .env and adjust values for your machine.`n`n# Environment mode: development | production`nENV=development`n`n# Required PostgreSQL DSN (must include +psycopg driver)`nDATABASE_URL=postgresql+psycopg://listing_lens:choose_a_password@localhost:5432/listing_lens_dev`n`n# Logging behavior`nLOG_LEVEL=INFO`nJSON_LOGS=false`n`n# Runtime toggles`nPII_ENABLED=true`nUSE_DB_SLUG_QUEUE=false`n`n# Photo storage backend configuration`nPHOTO_STORAGE_BACKEND=filesystem`nPHOTO_BASE_PATH=/mnt/nvme/photos`n" | Out-File -FilePath .env.example -Encoding utf8; Write-Host ".env.example created successfully." -ForegroundColor Green }

# Create a local development .env if missing.
setup-env:
    @if (Test-Path .env) { Write-Host ".env file already exists. Remove it first or edit manually." -ForegroundColor Yellow } else { "# Local development configuration`nENV=development`nDATABASE_URL=postgresql+psycopg://listing_lens:choose_a_password@localhost:5432/listing_lens_dev`nLOG_LEVEL=INFO`nJSON_LOGS=false`nPII_ENABLED=true`nUSE_DB_SLUG_QUEUE=false`nPHOTO_STORAGE_BACKEND=filesystem`nPHOTO_BASE_PATH=/mnt/nvme/photos" | Out-File -FilePath .env -Encoding utf8; Write-Host ".env file created successfully!" -ForegroundColor Green }

# Create a production-oriented .env if missing (Raspberry Pi service profile).
setup-env-prod:
    @if (Test-Path .env) { Write-Host ".env file already exists. Remove it first or edit manually." -ForegroundColor Yellow } else { "# Raspberry Pi production configuration`nENV=production`nDATABASE_URL=postgresql+psycopg://listing_lens:choose_a_password@localhost:5432/listing_lens`nLOG_LEVEL=INFO`nJSON_LOGS=true`nPII_ENABLED=true`nUSE_DB_SLUG_QUEUE=true`nPHOTO_STORAGE_BACKEND=filesystem`nPHOTO_BASE_PATH=/mnt/nvme/photos" | Out-File -FilePath .env -Encoding utf8; Write-Host "Production .env file created successfully!" -ForegroundColor Green }

# Collect Otodom slugs using the explicit developer preset from config/otodom.developer.yaml.
scrape-otodom-slugs:
    cd scrapy_project; poetry run scrapy crawl otodom_slugs -a config_file=../config/otodom.developer.yaml

# Collect Otodom slugs from one page only using the same developer preset.
scrape-otodom-slugs-1:
    cd scrapy_project; poetry run scrapy crawl otodom_slugs -a config_file=../config/otodom.developer.yaml -a max_pages=1

# Backward-compatible alias for previous recipe naming.
scrape-otodom-slugs-full: scrape-otodom-slugs

# Run local chained flow: otodom_slugs -> otodom_detail with the developer preset.
chain-otodom:
    poetry run python chain_otodom.py --config-file config/otodom.developer.yaml

# Run local chained flow with a one-page slug cap for quick validation.
chain-otodom-1:
    poetry run python chain_otodom.py --config-file config/otodom.developer.yaml --max-pages 1

# Backward-compatible alias for previous recipe naming.
chain-otodom-full: chain-otodom

# Create local scheduler manifest from the example if missing.
scheduler-init-manifest:
    @if (Test-Path config/spider_jobs.yaml) { Write-Host "config/spider_jobs.yaml already exists." -ForegroundColor Yellow } else { Copy-Item config/spider_jobs.example.yaml config/spider_jobs.yaml; Write-Host "Created config/spider_jobs.yaml from example." -ForegroundColor Green }

# Validate scheduler config and list registered jobs without starting the scheduling loop.
scheduler-dry-run:
    poetry run python main.py --jobs-file config/spider_jobs.yaml --dry-run

# Start APScheduler loop using the local jobs manifest.
scheduler-start:
    poetry run python main.py --jobs-file config/spider_jobs.yaml

# Run the full test suite.
test-all:
    poetry run pytest tests/ -v
