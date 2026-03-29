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

# ─── DOWNLOADER MIDDLEWARES ──────────────────────────────────
DOWNLOADER_MIDDLEWARES = {
    "scrapy_impersonate.RandomBrowserMiddleware": 500,
    "scrapy.downloadermiddlewares.useragent.UserAgentMiddleware": None,
    # NOTE: Scrapy's RetryMiddleware is disabled because scrapy-playwright has
    # its own built-in retry mechanism that handles browser-specific failures
    # more gracefully (e.g., navigation timeouts, page crashes).
    # The RETRY_* settings below are kept for documentation purposes but are
    # not actively used by the disabled middleware.
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
# NOTE: These settings are NOT ACTIVE because RetryMiddleware is disabled above.
# Retry behavior is handled by scrapy-playwright's built-in mechanisms.
# These settings are kept for reference and in case we need to re-enable
# Scrapy's retry middleware in the future.
RETRY_ENABLED = True  # Not used (middleware disabled)
RETRY_TIMES = 3       # Not used (middleware disabled)
RETRY_HTTP_CODES = [403, 429, 500, 502, 503, 504]  # Not used (middleware disabled)

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

# Configure structured logging if available
try:
    from logging_config import configure_logging
    configure_logging(
        log_level=LOG_LEVEL,
        log_dir=LOG_DIR,
        json_format=False,  # Set to True in production
        enable_file_logging=True,
    )
except ImportError:
    # Expected when logging_config.py is not available
    import logging
    logging.getLogger(__name__).info(
        "logging_config module not found, using Scrapy's default logging"
    )
except Exception as e:
    # Unexpected error - should be visible
    import logging
    logging.getLogger(__name__).error(
        f"Failed to configure structured logging: {e}",
        exc_info=True
    )
    # Fall back to Scrapy's default logging

# ─── FEED EXPORT ─────────────────────────────────────────────
FEED_EXPORT_ENCODING = "utf-8"

# ─── PIPELINES ───────────────────────────────────────────────
ITEM_PIPELINES = {
    "property_scraper.pipelines.ValidationPipeline": 100,
    "property_scraper.pipelines.PiiFilterPipeline": 200,
    "property_scraper.pipelines.PhotoDownloadPipeline": 300,
    # "property_scraper.pipelines.DatabasePipeline": 400,
}

# ─── PII FILTER ──────────────────────────────────────────────
# Set PII_ENABLED = False to bypass redaction entirely (e.g. in development).
PII_ENABLED = True
# Entity types forwarded to Presidio. Add "PERSON" here once a Polish spaCy
# model is available (see Stage B note in pii_filter.py).
PII_ENTITIES = ["PHONE_NUMBER", "EMAIL_ADDRESS", "URL", "PL_PESEL"]
# spaCy model used for tokenisation. Must be installed in the virtualenv.
# Use "pl_core_news_md" when enabling Polish NER (PII_ENTITIES += ["PERSON"]).
PII_NLP_MODEL = "en_core_web_sm"
# Language tag passed to Presidio Analyzer. Must match the NLP model family.
PII_LANGUAGE = "en"
# Minimum confidence score [0.0–1.0] below which a detection is ignored.
# Raise to e.g. 0.7 to suppress low-confidence hits.
PII_SCORE_THRESHOLD = 0.0
# Per-entity anonymization operators.  Keys are entity type strings (or the
# special key "DEFAULT" which applies to any entity without an explicit entry).
# Each value is a dict with a required "type" key (Presidio operator name) and
# optional operator-specific parameters.
#
# Supported operator types and their parameters:
#   replace   new_value (str)  — replace span with a fixed string
#   redact    —                — delete the span entirely
#   mask      masking_char (str), chars_to_mask (int), from_end (bool)
#   hash      hash_type ("sha256"|"sha512"|"md5")
#   encrypt   key (str, 128/192/256-bit base64)
#   keep      —                — leave span as-is (useful as DEFAULT)
#
# Examples:
#   PII_OPERATORS = {
#       "PHONE_NUMBER": {"type": "replace", "new_value": "<TELEFON>"},
#       "EMAIL_ADDRESS": {"type": "redact"},
#       "DEFAULT":       {"type": "replace", "new_value": "<PII>"},
#   }
PII_OPERATORS: dict = {}
