# property_scraper/settings.py

BOT_NAME = "property_scraper"
SPIDER_MODULES = ["property_scraper.spiders"]
NEWSPIDER_MODULE = "property_scraper.spiders"

# ─── REACTOR (required for scrapy-impersonate) ──────────────
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

# ─── TLS FINGERPRINT SPOOFING ───────────────────────────────
DOWNLOAD_HANDLERS = {
    "http": "scrapy_impersonate.ImpersonateDownloadHandler",
    "https": "scrapy_impersonate.ImpersonateDownloadHandler",
}

# ─── USER AGENT ROTATION ────────────────────────────────────
USER_AGENT = None  # Let scrapy-impersonate set UA matching TLS profile

DOWNLOADER_MIDDLEWARES = {
    "scrapy.downloadermiddlewares.useragent.UserAgentMiddleware": None,
    "scrapy.downloadermiddlewares.retry.RetryMiddleware": None,
    "scrapy_fake_useragent.middleware.RandomUserAgentMiddleware": 400,
    "scrapy_fake_useragent.middleware.RetryUserAgentMiddleware": 401,
    "scrapy_impersonate.RandomBrowserMiddleware": 1000,
}

FAKEUSERAGENT_PROVIDERS = [
    "scrapy_fake_useragent.providers.FakeUserAgentProvider",
    "scrapy_fake_useragent.providers.FakerProvider",
    "scrapy_fake_useragent.providers.FixedUserAgentProvider",
]
FAKEUSERAGENT_FALLBACK = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# ─── AUTOTHROTTLE ────────────────────────────────────────────
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 3.0
AUTOTHROTTLE_MAX_DELAY = 15.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0
AUTOTHROTTLE_DEBUG = False

# ─── DOWNLOAD DELAY (randomized) ────────────────────────────
DOWNLOAD_DELAY = 3
RANDOMIZE_DOWNLOAD_DELAY = True  # [0.5*delay, 1.5*delay]

# ─── CONCURRENCY ────────────────────────────────────────────
CONCURRENT_REQUESTS = 4
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

# ─── PIPELINES ───────────────────────────────────────────────
ITEM_PIPELINES = {
    "property_scraper.pipelines.ValidationPipeline": 100,
    "property_scraper.pipelines.DeduplicationPipeline": 200,
    "property_scraper.pipelines.PhotoDownloadPipeline": 300,
    "property_scraper.pipelines.DatabasePipeline": 400,
}
