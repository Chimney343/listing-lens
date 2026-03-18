---
applyTo: "**/spiders/**,**/scrapy_project/**,**/area_config*,**/items.py,**/pipelines.py,**/middlewares.py"
---

# Stage 1 — Scraping Layer (Scrapy)

## Objective

Build a Scrapy project with spiders for otodom.pl, gratka.pl, and morizon.pl. Each spider yields a standardized `RawListingItem`. Photos are downloaded as binary files via a Scrapy pipeline. Search areas are fully parameterized per spider via spider arguments.

## Dependencies

```
scrapy>=2.14
scrapy-impersonate>=1.6       # TLS/JA3 fingerprint spoofing via curl_cffi
scrapy-fake-useragent>=1.3    # Rotating UA from real browser stats
Pillow>=10.4
pydantic>=2.9
```

Optional (if otodom blocks impersonate-level requests):
```
scrapy-playwright>=0.0.41     # Fallback — headless browser via Scrapy
```

## Scrapy Anti-Bot Configuration (settings.py)

Hardened settings.py — every relevant built-in is maxed out for stealth.

```python
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
```

## Parameterized Search Areas

Every spider accepts area parameters via `-a` arguments. The search scope is never hardcoded.

```bash
# All of Kraków
scrapy crawl otodom -a city=krakow
# Specific districts
scrapy crawl otodom -a city=krakow -a districts=debniki,krowodrza,podgorze
# With price filter
scrapy crawl otodom -a city=krakow -a price_min=300000 -a price_max=700000
# Override max pages
scrapy crawl otodom -a city=krakow -a max_pages=5
```

### Area Config

```python
# property_scraper/area_config.py

from dataclasses import dataclass, field

@dataclass
class SearchArea:
    city: str = "krakow"
    voivodeship: str = "malopolskie"
    districts: list[str] = field(default_factory=list)  # empty = all
    price_min: int | None = None
    price_max: int | None = None
    area_min: float | None = None
    area_max: float | None = None
    rooms_min: int | None = None
    rooms_max: int | None = None
    max_pages: int = 20

OTODOM_DISTRICT_SLUGS = {
    "stare-miasto": "stare-miasto",
    "krowodrza": "krowodrza",
    "debniki": "debniki",
    "podgorze": "podgorze",
    "grzegorzki": "grzegorzki",
    "bronowice": "bronowice",
    "pradnik-bialy": "pradnik-bialy",
    "pradnik-czerwony": "pradnik-czerwony",
    "czyzyny": "czyzyny",
    "nowa-huta": "nowa-huta",
    "zwierzyniec": "zwierzyniec",
}

def build_otodom_url(area: SearchArea, page: int = 1) -> str:
    base = f"https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/{area.voivodeship}/{area.city}"
    params = [f"page={page}", "limit=36"]
    if area.price_min: params.append(f"priceMin={area.price_min}")
    if area.price_max: params.append(f"priceMax={area.price_max}")
    if area.area_min: params.append(f"areaMin={area.area_min}")
    if area.area_max: params.append(f"areaMax={area.area_max}")
    return f"{base}?{'&'.join(params)}"

def build_gratka_url(area: SearchArea, page: int = 1) -> str:
    base = f"https://gratka.pl/nieruchomosci/mieszkania/{area.city}/sprzedaz"
    params = [f"page={page}"]
    if area.price_min: params.append(f"cena-calkowita:min={area.price_min}")
    if area.price_max: params.append(f"cena-calkowita:max={area.price_max}")
    return f"{base}?{'&'.join(params)}"

def build_morizon_url(area: SearchArea, page: int = 1) -> str:
    base = f"https://www.morizon.pl/mieszkania/{area.city}"
    params = [f"page={page}"]
    if area.price_min: params.append(f"ps[price_from]={area.price_min}")
    if area.price_max: params.append(f"ps[price_to]={area.price_max}")
    return f"{base}/?{'&'.join(params)}"
```

**CAUTION**: URL query param formats for gratka and morizon are based on research and may not match current site behavior. Before implementing, manually perform a search on each portal and inspect the resulting URL. Update the builders accordingly.

## Otodom Spider

Otodom is a Next.js app. Listing data lives in `<script id="__NEXT_DATA__">` as JSON. Parse that, not HTML.

```python
# property_scraper/spiders/otodom.py

import scrapy, json
from datetime import datetime, timezone
from property_scraper.items import RawListingItem
from property_scraper.area_config import SearchArea, build_otodom_url

class OtodomSpider(scrapy.Spider):
    name = "otodom"
    allowed_domains = ["otodom.pl"]

    def __init__(self, city="krakow", districts="", price_min=None,
                 price_max=None, max_pages="20", **kwargs):
        super().__init__(**kwargs)
        self.area = SearchArea(
            city=city,
            districts=[d.strip() for d in districts.split(",") if d.strip()],
            price_min=int(price_min) if price_min else None,
            price_max=int(price_max) if price_max else None,
            max_pages=int(max_pages),
        )

    def start_requests(self):
        url = build_otodom_url(self.area, page=1)
        yield scrapy.Request(url, callback=self.parse_search, meta={"page": 1})

    def parse_search(self, response):
        next_data = response.css("script#__NEXT_DATA__::text").get()
        if not next_data:
            self.logger.warning(f"No __NEXT_DATA__ on {response.url}")
            return
        try:
            data = json.loads(next_data)
        except json.JSONDecodeError:
            self.logger.error(f"JSON decode failed: {response.url}")
            return

        page_props = data.get("props", {}).get("pageProps", {})
        search_data = page_props.get("data", {}).get("searchAds", {})
        items = search_data.get("items", [])

        for item in items:
            slug = item.get("slug", "")
            if not slug:
                continue
            yield scrapy.Request(
                f"https://www.otodom.pl/pl/oferta/{slug}",
                callback=self.parse_detail,
            )

        # Paginate
        current_page = response.meta["page"]
        total_pages = search_data.get("pagination", {}).get("totalPages", 1)
        if current_page < min(total_pages, self.area.max_pages):
            yield scrapy.Request(
                build_otodom_url(self.area, page=current_page + 1),
                callback=self.parse_search,
                meta={"page": current_page + 1},
            )

    def parse_detail(self, response):
        next_data = response.css("script#__NEXT_DATA__::text").get()
        if not next_data:
            return
        try:
            data = json.loads(next_data)
        except json.JSONDecodeError:
            return

        ad = data.get("props", {}).get("pageProps", {}).get("ad")
        if not ad:
            return  # soft 404

        images = ad.get("images", [])
        photo_urls = [img.get("large", img.get("medium", "")) for img in images if img]
        chars = {c["key"]: c["value"] for c in ad.get("characteristics", []) if "key" in c}

        item = RawListingItem()
        item["source_portal"] = "otodom"
        item["source_url"] = response.url
        item["external_id"] = str(ad.get("id", ""))
        item["title"] = ad.get("title", "")
        item["description"] = ad.get("description", "")
        item["city"] = "Kraków"
        loc = ad.get("location", {}).get("address", {})
        item["district"] = (loc.get("district") or {}).get("name")
        item["street"] = (loc.get("street") or {}).get("name")
        coords = ad.get("location", {}).get("coordinates", {})
        item["latitude"] = coords.get("latitude")
        item["longitude"] = coords.get("longitude")
        item["price_pln"] = self._extract_price(ad.get("totalPrice"))
        item["price_per_m2"] = self._extract_price(ad.get("pricePerSquareMeter"))
        item["area_m2"] = float(chars.get("m", 0)) or ad.get("areaInSquareMeters")
        item["rooms"] = self._safe_int(chars.get("rooms_num")) or ad.get("roomsNumber")
        item["floor"] = self._parse_floor(chars.get("floor_no"))
        item["total_floors"] = self._safe_int(chars.get("building_floors_num"))
        item["year_built"] = self._safe_int(chars.get("build_year"))
        item["has_lift"] = chars.get("lift") == "yes"
        features_str = str(ad.get("features", []))
        item["has_balcony"] = "balcony" in features_str
        item["has_terrace"] = "terrace" in features_str
        item["has_storage"] = "basement" in features_str
        item["heating_type"] = chars.get("heating")
        item["parking"] = chars.get("parking")
        item["building_material"] = chars.get("building_material")
        item["market_type"] = ad.get("market")
        item["listing_type"] = "agency" if ad.get("agency") else "private"
        item["date_posted"] = ad.get("dateCreated")
        item["date_scraped"] = datetime.now(timezone.utc).isoformat()
        item["photo_urls"] = photo_urls
        item["photo_count"] = len(photo_urls)
        item["description_length"] = len(item["description"])
        item["has_floor_plan"] = any("plan" in (u or "").lower() or "rzut" in (u or "").lower() for u in photo_urls)
        item["raw_json"] = ad
        yield item

    @staticmethod
    def _extract_price(val):
        if isinstance(val, dict):
            return val.get("value")
        return val

    @staticmethod
    def _safe_int(val):
        try:
            return int(val) if val else None
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_floor(floor_str):
        if not floor_str:
            return None
        if floor_str in ("ground_floor", "parter"):
            return 0
        try:
            return int(floor_str)
        except (ValueError, TypeError):
            return None
```

## Gratka & Morizon Spiders

Same `__init__` signature for parameterization. Use `response.css()` for HTML parsing. Define all selectors as class-level constants for easy maintenance when site structure changes.

## Scrapy Pipelines

```python
# property_scraper/pipelines.py

import hashlib
import scrapy

class ValidationPipeline:
    def process_item(self, item, spider):
        if not item.get("source_url"):
            raise scrapy.exceptions.DropItem("Missing source_url")
        if not item.get("title"):
            raise scrapy.exceptions.DropItem(f"Missing title: {item.get('source_url')}")
        if not item.get("price_pln") and not item.get("area_m2"):
            raise scrapy.exceptions.DropItem(f"No price or area: {item.get('source_url')}")
        return item

class DeduplicationPipeline:
    def process_item(self, item, spider):
        parts = "|".join([
            str(item.get("district", "none")).lower().strip(),
            f"{item.get('area_m2', 0):.1f}" if item.get("area_m2") else "none",
            str(item.get("floor", "none")),
            str(item.get("price_pln", "none")),
            str(item.get("rooms", "none")),
            str(item.get("street", "none")).lower().strip(),
        ])
        item["listing_hash"] = hashlib.sha256(parts.encode()).hexdigest()[:16]
        return item
```

PhotoDownloadPipeline and DatabasePipeline are stubs here — full implementation depends on Stage 3 (Storage).

## Soft 404 Detection

Otodom: `"ad": null` in `__NEXT_DATA__`. Gratka: "Oferta nieaktualna" in body. Morizon: "Ogłoszenie wygasło" in body. All spiders should check these before yielding items.

## Known Risks

| Risk | Mitigation |
|------|------------|
| otodom changes `__NEXT_DATA__` structure or migrates to RSC flight data | Monitor for 0-item runs; install `njsparser` as fallback for RSC |
| scrapy-impersonate TLS profiles get stale | Update library regularly; fall back to scrapy-playwright |
| Gratka/Morizon change HTML selectors | Define selectors as constants; test weekly |
| `CrawlerProcess.start()` calls `reactor.run()` once | Use `CrawlerRunner` + asyncio for multi-spider scheduler integration |

## Testing

1. `scrapy shell "https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/malopolskie/krakow"` — inspect `__NEXT_DATA__`
2. Run each spider with `-a max_pages=1` — verify item fields
3. Enable `HTTPCACHE_ENABLED=True` during dev to avoid repeated portal hits
4. Set `AUTOTHROTTLE_DEBUG=True` — verify adaptive delays
5. Test `-a districts=debniki` — verify correct filtering
