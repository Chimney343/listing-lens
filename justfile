# Property Pipeline — Kraków
# Run with: just <recipe>
# Each scrape creates a timestamped directory under data/otodom/ with slug_run_meta.jsonl, slug_collection.jsonl, output.jsonl, and rejected_otodom.jsonl

set shell := ["powershell", "-Command"]

# Make root-level modules (e.g. otodom_config) importable when scrapy runs from scrapy_project/
export PYTHONPATH := justfile_directory()

# Collect slugs from page 1 only (quick test / preview)
scrape-otodom-slugs-1:
    cd scrapy_project; poetry run scrapy crawl otodom_slugs -a max_pages=1

# Collect all slugs with default settings (full run)
scrape-otodom-slugs-full:
    cd scrapy_project; poetry run scrapy crawl otodom_slugs

# Chain slug collection + detail scraping, 1 page (quick local end-to-end test)
chain-otodom-1:
    poetry run python chain_otodom.py --max-pages 1

# Chain slug collection + detail scraping, full run
chain-otodom-full:
    poetry run python chain_otodom.py

# Run all tests (sequential comprehensive)
test-all:
    poetry run pytest tests/ -v

# Set up .env file with default configuration
setup-env:
    @if (Test-Path .env) { Write-Host ".env file already exists. Remove it first or edit manually." -ForegroundColor Yellow } else { "DATABASE_URL=postgresql://listing_lens:choose_a_password@localhost:5432/listing_lens_dev`nPHOTO_STORAGE_BACKEND=filesystem`nPHOTO_STORAGE_PATH=/mnt/nvme/photos" | Out-File -FilePath .env -Encoding utf8; Write-Host ".env file created successfully!" -ForegroundColor Green }
