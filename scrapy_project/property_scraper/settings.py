"""Scrapy settings for the property scraper project."""

import os
import sys
from pathlib import Path

BOT_NAME = "property_scraper"
SPIDER_MODULES = ["property_scraper.spiders"]
NEWSPIDER_MODULE = "property_scraper.spiders"

# ─── PROJECT PATHS ──────────────────────────────────────────
DATA_DIR = str(Path(__file__).resolve().parents[2] / "data")

# ─── REACTOR (required for scrapy-impersonate) ──────────────
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

# ─── DOWNLOAD HANDLERS ──────────────────────────────────────
# Playwright for browser-based requests.
DOWNLOAD_HANDLERS = {
    "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
}

# ─── PLAYWRIGHT ──────────────────────────────────────────────
PLAYWRIGHT_BROWSER_TYPE = "chromium"
PLAYWRIGHT_LAUNCH_OPTIONS = {
    "headless": True,
    "args": [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
    ],
}
PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT = 30_000

# Block resource types that are irrelevant to scraping.
# This eliminates ~35k sub-requests per full run, reduces memory pressure,
# and prevents "Task was destroyed but it is pending!" from in-flight resources.
# "fetch" and "document" must remain allowed — otodom uses fetch for API calls.
PLAYWRIGHT_ABORT_REQUEST = lambda req: req.resource_type in {
    "image", "media", "font", "ping", "websocket",
}
PLAYWRIGHT_CONTEXTS = {
    "default": {
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "viewport": {"width": 1920, "height": 1080},
        "locale": "pl-PL",
        "timezone_id": "Europe/Warsaw",
        "extra_http_headers": {
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
        },
    }
}

# ─── USER AGENT ─────────────────────────────────────────────
# Playwright requests use real Chromium UA automatically.
# Non-playwright requests use this fallback.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

DOWNLOADER_MIDDLEWARES = {
    "scrapy_impersonate.RandomBrowserMiddleware": 500,
    "scrapy.downloadermiddlewares.useragent.UserAgentMiddleware": None,
    "scrapy.downloadermiddlewares.retry.RetryMiddleware": None,
}

# ─── AUTOTHROTTLE ────────────────────────────────────────────
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 3.0
AUTOTHROTTLE_MAX_DELAY = 15.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 2.0
AUTOTHROTTLE_DEBUG = False

# ─── DOWNLOAD DELAY (randomized) ────────────────────────────
DOWNLOAD_DELAY = 12
RANDOMIZE_DOWNLOAD_DELAY = True  # [0.5*delay, 1.5*delay]

# ─── CONCURRENCY ────────────────────────────────────────────
CONCURRENT_REQUESTS = 8
CONCURRENT_REQUESTS_PER_DOMAIN = 1
CONCURRENT_ITEMS = 50

# ─── COOKIES ─────────────────────────────────────────────────
COOKIES_ENABLED = True
COOKIES_DEBUG = False

# ─── HTTP CACHE (enable during development only) ────────────
# HTTPCACHE_ENABLED = True
# HTTPCACHE_EXPIRATION_SECS = 86400
# HTTPCACHE_DIR = "httpcache"
# HTTPCACHE_STORAGE = "scrapy.extensions.httpcache.FilesystemCacheStorage"

# ─── RETRY ───────────────────────────────────────────────────
RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [403, 429, 500, 502, 503, 504]

# ─── HEADERS ─────────────────────────────────────────────────
DEFAULT_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

# ─── ROBOTS.TXT ──────────────────────────────────────────────
ROBOTSTXT_OBEY = False  # Portals block scrapers via robots.txt

# ─── LOGGING ─────────────────────────────────────────────────
LOG_LEVEL = "INFO"
LOG_ENCODING = "utf-8"
LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
LOG_DATEFORMAT = "%Y-%m-%d %H:%M:%S"

# Silence loggers that produce per-item/per-request debug noise.
# scrapy.core.scraper dumps the full item repr after each scrape — redundant
# since items are already written to output.jsonl.
import logging as _logging
_logging.getLogger("scrapy.core.scraper").setLevel(_logging.WARNING)
_logging.getLogger("scrapy.core.engine").setLevel(_logging.WARNING)
_logging.getLogger("scrapy-playwright").setLevel(_logging.WARNING)
_logging.getLogger("playwright").setLevel(_logging.WARNING)

LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
DATABASE_URL = os.environ.get("DATABASE_URL")

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from logging_config import configure_logging
    configure_logging(
        log_level=LOG_LEVEL,
        log_dir=LOG_DIR,
        json_format=False,  # Set to True in production
        enable_file_logging=True,
    )
except ImportError:
    pass  # Fall back to Scrapy's default logging

# ─── FEED EXPORT ─────────────────────────────────────────────
FEED_EXPORT_ENCODING = "utf-8"

# ─── PIPELINES ───────────────────────────────────────────────
ITEM_PIPELINES = {
    "property_scraper.pipelines.ValidationPipeline": 100,
    "property_scraper.pipelines.PhotoDownloadPipeline": 300,
    # "property_scraper.pipelines.DatabasePipeline": 400,
}
