# Property Pipeline — Kraków
# Run with: just <recipe>
# Each scrape creates a timestamped directory under data/otodom/ with slug_runs.jsonl, output.jsonl, and rejected_otodom.jsonl

set shell := ["powershell", "-Command"]

# Make root-level modules (e.g. otodom_config) importable when scrapy runs from scrapy_project/
export PYTHONPATH := justfile_directory()

# Collect slugs from page 1 only (quick test / preview)
scrape-otodom-slugs-1:
    cd scrapy_project; poetry run scrapy crawl otodom_slugs -a max_pages=1

# Collect slugs — dom (house) listings, page 1
scrape-otodom-dom-1:
    cd scrapy_project; poetry run scrapy crawl otodom_slugs -a max_pages=1 -a property_type=dom

# Collect all slugs with default settings (full run)
scrape-otodom-slugs-full:
    cd scrapy_project; poetry run scrapy crawl otodom_slugs

# Scrape detail pages for a comma-separated list of slugs
# Usage: just scrape-otodom-detail slugs=slug1,slug2,...
scrape-otodom-detail slugs="":
    cd scrapy_project; poetry run scrapy crawl otodom_detail -a slugs={{slugs}}

# Chain slug collection + detail scraping, 1 page (quick local end-to-end test)
chain-otodom-1:
    poetry run python chain_otodom.py --max-pages 1

# Chain slug collection + detail scraping, full run
chain-otodom-full:
    poetry run python chain_otodom.py

# Scrape Dębica (Podkarpackie, Dębicki powiat, gmina‑miejska‑‑dębica)
scrape-debica:
    poetry run python chain_otodom.py \
        --city debica \
        --voivodeship podkarpackie \
        --powiat debicki \
        --gmina gmina-miejska--debica \
        --property-type mieszkanie

# ─── Testing ────────────────────────────────────────────────────────────────

# Run all otodom spider tests (sequential)
test-otodom:
    poetry run pytest tests/test_otodom_spider.py -v

# Run all stealth technique tests (sequential)
test-stealth:
    poetry run pytest tests/test_stealth_techniques.py -v

# Run both test suites in parallel using PowerShell jobs
test-otodom-parallel:
    $job1 = Start-Job -ScriptBlock { Set-Location $using:PWD; poetry run pytest tests/test_otodom_spider.py -v }; $job2 = Start-Job -ScriptBlock { Set-Location $using:PWD; poetry run pytest tests/test_stealth_techniques.py -v }; $jobs = @($job1, $job2); $jobs | Wait-Job | Out-Null; $jobs | Receive-Job; $failed = $jobs | Where-Object { $_.State -ne 'Completed' }; Remove-Job $jobs; if ($failed) { Write-Host "Some tests failed!" -ForegroundColor Red; exit 1 } else { Write-Host "All parallel tests passed!" -ForegroundColor Green }

# Run all tests (sequential comprehensive)
test-all:
    poetry run pytest tests/ -v

# Run tests with coverage report
test-coverage:
    poetry run pytest tests/ --cov=scrapy_project/property_scraper --cov-report=term-missing

# ─── Development ────────────────────────────────────────────────────────────

# Install test dependencies
test-deps:
    poetry add --group dev pytest pytest-asyncio pytest-mock pytest-cov freezegun

# Quick test of a single test file
test-quick file="test_otodom_spider.py":
    poetry run pytest tests/{{file}} -v -x
