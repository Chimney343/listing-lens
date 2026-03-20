# Property Pipeline — Kraków
# Run with: just <recipe>
# Each scrape creates a timestamped directory under data/otodom/ with slug_runs.jsonl, output.jsonl, and rejected_otodom.jsonl

set shell := ["powershell", "-Command"]

# Scrape first page of Otodom only (quick test / preview)
scrape-otodom-1:
    cd scrapy_project; poetry run scrapy crawl otodom -a max_pages=1

# Scrape first page of Otodom — dom (house) listings
scrape-otodom-dom-1:
    cd scrapy_project; poetry run scrapy crawl otodom -a max_pages=1 -a property_type=dom

# Scrape Otodom with default settings (full run)
scrape-otodom-full:
    cd scrapy_project; poetry run scrapy crawl otodom

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
