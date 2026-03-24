import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import scrapy
from itemloaders.processors import TakeFirst
from scrapy.loader import ItemLoader
from scrapy_playwright.page import PageMethod

try:
    from otodom_config import OtodomSpiderConfig
except ImportError:
    # Fallback for when running from scrapy_project directory
    import sys
    sys.path.insert(0, '..')
    from otodom_config import OtodomSpiderConfig

from property_scraper.area_config import SearchArea, build_otodom_url
from property_scraper.items import RawListingItem, RawJsonItem


_STEALTH_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    window.chrome = {runtime: {}};
    Object.defineProperty(navigator, 'languages', {get: () => ['pl-PL', 'pl', 'en-US', 'en']});
    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
"""

# Intercepts window.fetch on investment pages to capture the
# PaginatedInvestmentUnits API URL (which contains the sha256Hash).
_CAPTURE_FETCH_SCRIPT = """
    const _origFetch = window.fetch;
    window.__investmentApiUrl = null;
    window.fetch = function(...args) {
        const url = typeof args[0] === 'string' ? args[0]
                  : (args[0] && args[0].url ? args[0].url : '');
        if (url.includes('PaginatedInvestmentUnits')) {
            window.__investmentApiUrl = url;
        }
        return _origFetch.apply(this, args);
    };
"""

# Runs after networkidle: reads the intercepted URL, extracts the hash and ad_id,
# then issues paginated fetch calls (using the page's own session/cookies) with
# pageSize=200 so all units come back without separate httpx calls.
_UNITS_FETCH_SCRIPT = """
async () => {
    if (!window.__investmentApiUrl) return null;
    let ad_id, sha256Hash;
    try {
        const u = new URL(window.__investmentApiUrl, window.location.origin);
        const vars = JSON.parse(u.searchParams.get('variables') || '{}');
        const exts = JSON.parse(u.searchParams.get('extensions') || '{}');
        ad_id = vars.id;
        sha256Hash = exts && exts.persistedQuery && exts.persistedQuery.sha256Hash;
    } catch (e) {
        return { error: 'parse_failed', message: String(e) };
    }
    if (!ad_id || !sha256Hash) return { error: 'missing_params' };

    const allItems = [];
    let page = 1, totalPages = 1;
    do {
        const vars = JSON.stringify({
            id: ad_id,
            lookup: { filters: { numberOfRooms: [] }, page, pageSize: 200,
                      sort: { by: 'Price', direction: 'asc' }, withFacets: true }
        });
        const exts = JSON.stringify({ persistedQuery: { sha256Hash, version: 1 } });
        const params = new URLSearchParams({
            operationName: 'PaginatedInvestmentUnits',
            variables: vars, extensions: exts
        });
        const resp = await fetch('/api/query?' + params.toString());
        if (!resp.ok) return { error: resp.status, sha256Hash };
        const data = await resp.json();
        const paginated = data && data.data && data.data.paginatedUnits;
        if (!paginated) return { error: 'no_data', sha256Hash };
        allItems.push.apply(allItems, paginated.items || []);
        totalPages = (paginated.pagination && paginated.pagination.totalPages) || 1;
        page++;
    } while (page <= totalPages);
    return { sha256Hash, ad_id, items: allItems };
}
"""


async def _page_init(page, request):
    await page.add_init_script(_STEALTH_SCRIPT)


async def _page_init_investment(page, request):
    """Init script for investment pages: stealth + fetch interceptor."""
    await page.add_init_script(_STEALTH_SCRIPT + _CAPTURE_FETCH_SCRIPT)


def _pw_meta(investment: bool = False) -> dict:
    """Return Playwright request meta.  Pass investment=True for investment pages."""
    init_cb = _page_init_investment if investment else _page_init
    methods: list = [PageMethod("wait_for_load_state", "networkidle", timeout=30_000)]
    if investment:
        methods.append(PageMethod("evaluate", _UNITS_FETCH_SCRIPT))
    return {
        "playwright": True,
        "playwright_context": "default",
        "playwright_page_init_callback": init_cb,
        "playwright_page_methods": methods,
    }


_PROPERTY_TYPE_MAP = {"mieszkanie": "apartment", "dom": "house"}


# ─────────────────────────────────────────────────────────────────────────────
# Spider 1 of 2: slug collection
# ─────────────────────────────────────────────────────────────────────────────

class OtodomSlugSpider(scrapy.Spider):
    """Crawls Otodom search pages and collects all listing slugs.

    Handles investment expansion (phase 1.5) internally — no detail pages
    are visited and no RawListingItem is yielded.  After completion the full
    slug list is written to run_dir/slug_runs.jsonl so that OtodomDetailSpider
    (or the scheduler) can pick it up.

    Usage:
        scrapy crawl otodom_slugs [-a city=...] [-a max_pages=1]
    """

    name = "otodom_slugs"
    allowed_domains = ["otodom.pl"]

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        spider.run_dir.mkdir(parents=True, exist_ok=True)
        return spider

    def __init__(
        self,
        city: str = "mielec",
        voivodeship: str = "podkarpackie",
        powiat: str = "mielecki",
        gmina: str = "gmina-miejska--mielec",
        property_type: str = "mieszkanie",
        districts: str = "",
        price_min: str | None = None,
        price_max: str | None = None,
        max_pages: str | None = None,
        config: Optional[OtodomSpiderConfig] = None,
        config_file: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)

        if config_file is not None:
            try:
                from otodom_config import load_config_from_file
                config = load_config_from_file(config_file)
                self.logger.info("Loaded config from file: %s", config_file)
            except Exception as e:
                self.logger.error("Failed to load config from %s: %s", config_file, e)
                raise

        if config is not None:
            city = config.city
            voivodeship = config.voivodeship
            powiat = config.powiat
            gmina = config.gmina
            property_type = config.property_type
            districts = config.districts
            price_min = config.price_min
            price_max = config.price_max
            max_pages = config.max_pages

        self._parameters = {
            "city": city,
            "voivodeship": voivodeship,
            "powiat": powiat,
            "gmina": gmina,
            "property_type": property_type,
            "districts": districts,
            "price_min": price_min,
            "price_max": price_max,
            "max_pages": max_pages,
        }

        self.run_timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._start_time = None
        self._end_time = None
        self._run_dir = None

        if config is not None:
            self.area = config.to_search_area()
        else:
            self.area = SearchArea(
                city=city,
                voivodeship=voivodeship,
                powiat=powiat,
                gmina=gmina,
                property_type=property_type,
                districts=[d.strip() for d in districts.split(",") if d.strip()],
                price_min=int(price_min) if price_min and price_min.lower() != "null" else None,
                price_max=int(price_max) if price_max and price_max.lower() != "null" else None,
                max_pages=int(max_pages) if max_pages and max_pages.lower() != "null" else None,
            )

    @property
    def run_dir(self) -> Path:
        if self._run_dir is None:
            data_dir = Path(self.settings.get("DATA_DIR"))
            self._run_dir = data_dir / "otodom" / self.run_timestamp
        return self._run_dir

    # ─── Phase 1: collect slugs from all search pages ────────────

    async def start(self):
        self._start_time = datetime.now(timezone.utc)
        price_range = f"{self.area.price_min or '?'}–{self.area.price_max or '?'} PLN"
        self.logger.info(
            "Starting slug collection: city=%s, type=%s, price=%s, max_pages=%s",
            self.area.city,
            self.area.property_type,
            price_range,
            "all" if self.area.max_pages is None else str(self.area.max_pages),
        )
        url = build_otodom_url(self.area, page=1)
        yield scrapy.Request(url, callback=self._bootstrap, meta={"page": 1, **_pw_meta()})

    def _bootstrap(self, response):
        """Fetch page 1, discover pagination, fan out to all remaining search pages."""
        search_data = self._parse_search_data(response)
        if search_data is None:
            return

        pagination = search_data.get("pagination", {})
        self._total_items: int = pagination.get("totalItems", 0)
        total_pages: int = pagination.get("totalPages", 1)
        self._total_pages: int = (
            total_pages
            if self.area.max_pages is None
            else min(total_pages, self.area.max_pages)
        )
        self._slugs: set[str] = set()
        self._investments: dict[int, tuple[str, int]] = {}  # ad_id → (slug, expected_units)
        self._search_pages_received: int = 0

        self.logger.info(
            "Bootstrap: API reports %d items across %d pages%s",
            self._total_items,
            total_pages,
            f" (capped at {self._total_pages})" if self.area.max_pages is not None else "",
        )

        self._absorb_search_items(search_data, page=1)
        self._search_pages_received += 1

        for page in range(2, self._total_pages + 1):
            yield scrapy.Request(
                build_otodom_url(self.area, page=page),
                callback=self._collect_slugs,
                errback=self._on_search_error,
                meta={"page": page, **_pw_meta()},
            )

        if self._search_pages_received == self._total_pages:
            yield from self._finish_search_collection()

    def _collect_slugs(self, response):
        """Collect slugs from a follow-up search page; trigger next phase when done."""
        search_data = self._parse_search_data(response)
        if search_data is not None:
            self._absorb_search_items(search_data, page=response.meta["page"])
        self._search_pages_received += 1

        if self._search_pages_received == self._total_pages:
            yield from self._finish_search_collection()

    def _absorb_search_items(self, search_data: dict, page: int) -> None:
        """Extract slugs from a search page, separating investments from regular listings."""
        before = len(self._slugs)
        for item in search_data.get("items", []):
            slug = item.get("slug", "")
            if not slug:
                continue
            if item.get("estate") == "INVESTMENT":
                ad_id = item.get("id")
                if ad_id:
                    is_new = ad_id not in self._investments
                    expected = item.get("investmentUnitsNumber", 0)
                    self._investments[ad_id] = (slug, expected)
                    if is_new:
                        self.logger.info(
                            "  Investment detected: %s (id=%s, %d units)",
                            slug,
                            ad_id,
                            expected,
                        )
                    else:
                        self.logger.debug(
                            "  Investment re-seen on page %d: %s", page, slug
                        )
            else:
                self._slugs.add(slug)
        added = len(self._slugs) - before
        inv_part = (
            f", {len(self._investments)} investment(s)" if self._investments else ""
        )
        self.logger.info(
            "Search page %d/%d: +%d slugs (total: %d%s)",
            page,
            self._total_pages,
            added,
            len(self._slugs),
            inv_part,
        )

    # ─── Phase 1.5: expand investments into unit slugs ───────────

    def _finish_search_collection(self):
        """After all search pages collected, expand investments or finish."""
        listing_count = len(self._slugs)
        investment_count = len(self._investments)
        self.logger.info(
            "Search complete: %d listing slugs + %d investments",
            listing_count,
            investment_count,
        )

        if investment_count > 0:
            total_expected_units = sum(u for _, u in self._investments.values())
            self.logger.info(
                "Phase 1.5: expanding %d investment(s) — %d units expected",
                investment_count,
                total_expected_units,
            )
            self._investment_responses_pending = investment_count
            for ad_id, (inv_slug, expected_units) in self._investments.items():
                yield scrapy.Request(
                    f"https://www.otodom.pl/pl/inwestycja/{inv_slug}",
                    callback=self._on_investment_page,
                    errback=self._on_investment_error,
                    meta={
                        "ad_id": ad_id,
                        "inv_slug": inv_slug,
                        "expected_units": expected_units,
                        **_pw_meta(investment=True),
                    },
                )
        else:
            self._finish_all_collection()

    def _on_investment_page(self, response):
        """Extract unit slugs from an investment page via the intercepted API call."""
        ad_id = response.meta["ad_id"]
        inv_slug = response.meta["inv_slug"]
        expected_units = response.meta["expected_units"]

        self._slugs.add(inv_slug)

        result = None
        for pm in response.meta.get("playwright_page_methods", []):
            if pm.method == "evaluate" and isinstance(pm.result, dict):
                result = pm.result
                break

        if not result or result.get("error"):
            self.logger.error(
                "Investment %s (id=%d): could not fetch units via API (%s) "
                "— falling back to HTML link extraction",
                inv_slug,
                ad_id,
                result,
            )
            self._extract_units_from_html(response, inv_slug)
            self._investment_responses_pending -= 1
            if self._investment_responses_pending == 0:
                self._finish_all_collection()
            return

        sha256_hash = result["sha256Hash"]
        items = result.get("items", [])
        total = len(items)

        if expected_units and total != expected_units:
            self.logger.warning(
                "Investment %s: expected %d units but API returned %d",
                inv_slug,
                expected_units,
                total,
            )

        for unit in items:
            unit_url = unit.get("url", "")
            if unit_url:
                self._slugs.add(unit_url.rstrip("/").split("/")[-1])

        self.logger.info(
            "Investment %s: %d/%d units collected (hash %.8s…)",
            inv_slug,
            total,
            expected_units or total,
            sha256_hash,
        )

        self._investment_responses_pending -= 1
        if self._investment_responses_pending == 0:
            self._finish_all_collection()

    def _extract_units_from_html(self, response, inv_slug: str) -> None:
        """Fallback: scrape unit slugs from <a> tags on the investment page."""
        links = response.css('a[href*="/pl/oferta/"]::attr(href)').getall()
        unit_slugs = set()
        for href in links:
            m = re.search(r"/pl/oferta/([a-zA-Z0-9-]+)", href)
            if m:
                unit_slugs.add(m.group(1))
        unit_slugs.discard(inv_slug)
        self._slugs.update(unit_slugs)
        self.logger.warning(
            "Investment %s: HTML fallback collected %d unit slugs (may be incomplete)",
            inv_slug,
            len(unit_slugs),
        )

    # ─── Error handlers ──────────────────────────────────────────

    def _on_search_error(self, failure):
        """Handle failed search page request."""
        self.logger.error("Search page request failed: %s", failure.value)
        self._search_pages_received += 1
        if self._search_pages_received == self._total_pages:
            yield from self._finish_search_collection()

    def _on_investment_error(self, failure):
        """Handle failed investment page load."""
        self.logger.error("Investment page request failed: %s", failure.value)
        self._investment_responses_pending -= 1
        if self._investment_responses_pending == 0:
            self._finish_all_collection()

    # ─── Slug persistence ─────────────────────────────────────────

    def _build_slug_run_record(self) -> dict:
        investment_count = len(self._investments)
        return {
            "run_id": self.run_timestamp,
            "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "record_type": "slug_collection",
            "parameters": self._parameters,
            "city": self.area.city,
            "total_advertised": self._total_items,
            "investments_found": investment_count,
            "investment_slugs": {
                str(k): {"slug": slug, "expected_units": units}
                for k, (slug, units) in self._investments.items()
            },
            "slug_count": len(self._slugs),
            "slugs": sorted(self._slugs),
        }

    def _persist_slug_run(self) -> None:
        record = self._build_slug_run_record()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        slug_runs_file = self.run_dir / "slug_runs.jsonl"
        with open(slug_runs_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

        investment_count = len(self._investments)
        total_investment_slugs = (
            sum(u for _, u in self._investments.values()) + investment_count
        )
        regular_count = len(self._slugs) - total_investment_slugs
        inv_detail = (
            f" + {total_investment_slugs} from {investment_count} investment(s)"
            if investment_count
            else ""
        )
        self.logger.info(
            "Slug collection complete: %d total (%d regular%s). Saved to %s",
            len(self._slugs),
            regular_count,
            inv_detail,
            slug_runs_file,
        )

    def _finish_all_collection(self):
        """All slugs and investments resolved.  Persist and stop."""
        self._persist_slug_run()
        self.logger.info(
            "Done. Run detail spider:  scrapy crawl otodom_detail -a city=%s -a slugs=<paste from slug_runs.jsonl>",
            self.area.city,
        )

    # ─── Shared helpers ──────────────────────────────────────────

    def _parse_search_data(self, response) -> dict | None:
        next_data_raw = response.css("script#__NEXT_DATA__::text").get()
        if not next_data_raw:
            self.logger.warning("No __NEXT_DATA__ on %s", response.url)
            return None
        try:
            data = json.loads(next_data_raw)
        except json.JSONDecodeError:
            self.logger.error("JSON decode failed: %s", response.url)
            return None
        return (
            data.get("props", {})
            .get("pageProps", {})
            .get("data", {})
            .get("searchAds", {})
        )

    def closed(self, reason):
        self._end_time = datetime.now(timezone.utc)
        if hasattr(self, "run_dir") and self.run_dir and self._start_time:
            try:
                slug_runs_file = self.run_dir / "slug_runs.jsonl"
                runtime_seconds = (self._end_time - self._start_time).total_seconds()
                completion_record = {
                    "run_id": self.run_timestamp,
                    "start_time": self._start_time.isoformat(timespec="seconds"),
                    "end_time": self._end_time.isoformat(timespec="seconds"),
                    "runtime_seconds": runtime_seconds,
                    "runtime_human": f"{runtime_seconds:.1f}s",
                    "parameters": self._parameters,
                    "completion_reason": reason,
                    "record_type": "completion",
                }
                with open(slug_runs_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(completion_record) + "\n")
                self.logger.info(
                    "Spider completed in %.1f seconds. Reason: %s",
                    runtime_seconds,
                    reason,
                )
            except OSError as e:
                self.logger.exception("Failed to write completion record: %s", e)


# ─────────────────────────────────────────────────────────────────────────────
# Spider 2 of 2: detail scraping
# ─────────────────────────────────────────────────────────────────────────────

class OtodomDetailSpider(scrapy.Spider):
    """Visits individual Otodom advert pages and yields RawListingItem.

    Three invocation modes, selected automatically by priority:

    1. **Single-slug mode**: ``-a slug=some-slug``.
    2. **Inline mode**: ``-a slugs=slug1,slug2,...`` or ``-a slugs_file=/path/to/slugs.txt``
       (one slug per line). ``slugs_file`` avoids Windows CLI length limits.
    3. **Slug-run file mode**: ``-a slug_run_file=/path/to/slug_runs.jsonl``.
       Reads the ``slug_collection`` record written by :class:`OtodomSlugSpider`
       and scrapes every slug it contains.  This is the canonical hand-off
       between the two spiders when running locally via ``chain_otodom.py``.
    4. **Database mode** (not yet implemented): when none of the above are
       given the spider will query the DB for stale slugs.

    Usage::

        scrapy crawl otodom_detail -a slug=some-listing-slug
        scrapy crawl otodom_detail -a slugs=slug1,slug2,...
        scrapy crawl otodom_detail -a slugs_file=/tmp/slugs.txt
        scrapy crawl otodom_detail -a slug_run_file=data/otodom/20260324_215403/slug_runs.jsonl
    """

    name = "otodom_detail"
    allowed_domains = ["otodom.pl"]

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        spider.run_dir.mkdir(parents=True, exist_ok=True)
        parsed_path = str(spider.run_dir / "output.jsonl")
        raw_path = str(spider.run_dir / "raw_output.jsonl")
        crawler.settings.set(
            "FEEDS",
            {
                parsed_path: {
                    "format": "jsonlines",
                    "encoding": "utf-8",
                    "overwrite": True,
                    "item_classes": [RawListingItem],
                },
                raw_path: {
                    "format": "jsonlines",
                    "encoding": "utf-8",
                    "overwrite": True,
                    "item_classes": [RawJsonItem],
                },
            },
            priority="spider",
        )
        return spider

    def __init__(
        self,
        city: str = "",
        slugs: str = "",
        slug: str | None = None,
        slugs_file: str = "",
        slug_run_file: str = "",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.city = city
        self.single_slug = slug
        if slug_run_file:
            self._slugs_list: list[str] = self._read_slug_run_file(slug_run_file)
        elif slugs_file:
            slugs_path = Path(slugs_file)
            with open(slugs_path, encoding="utf-8") as f:
                self._slugs_list = [line.strip() for line in f if line.strip()]
        else:
            self._slugs_list = [s.strip() for s in slugs.split(",") if s.strip()]
        self.run_timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._start_time = None
        self._end_time = None
        self._run_dir = None
        self._detail_scraped = 0
        self._detail_total = 0

    @property
    def run_dir(self) -> Path:
        if self._run_dir is None:
            data_dir = Path(self.settings.get("DATA_DIR"))
            self._run_dir = data_dir / "otodom" / self.run_timestamp
        return self._run_dir

    async def start(self):
        self._start_time = datetime.now(timezone.utc)

        if self.single_slug:
            self.logger.info("Single-slug mode: scraping %s", self.single_slug)
            self._detail_total = 1
            yield scrapy.Request(
                f"https://www.otodom.pl/pl/oferta/{self.single_slug}",
                callback=self.parse_detail,
                errback=self._on_detail_error,
                meta=_pw_meta(),
            )
            return

        if self._slugs_list:
            self._detail_total = len(self._slugs_list)
            self.logger.info(
                "Inline mode: scraping %d slugs (city=%s)",
                self._detail_total,
                self.city or "unset",
            )
            for slug in self._slugs_list:
                yield scrapy.Request(
                    f"https://www.otodom.pl/pl/oferta/{slug}",
                    callback=self.parse_detail,
                    errback=self._on_detail_error,
                    meta=_pw_meta(),
                )
            return

        # DB mode — not yet implemented
        self.logger.error(
            "No slugs provided and database mode is not yet implemented. "
            "Pass -a slugs=slug1,slug2,... or -a slug=single-slug."
        )

    @staticmethod
    def _read_slug_run_file(path: str) -> list[str]:
        """Extract the slug list from a slug_runs.jsonl produced by OtodomSlugSpider."""
        p = Path(path)
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                if record.get("record_type") == "slug_collection":
                    return record.get("slugs", [])
        raise ValueError(
            f"No 'slug_collection' record found in {path}. "
            "Make sure otodom_slugs has completed successfully."
        )

    # ─── Detail parsing ───────────────────────────────────────────

    def parse_detail(self, response):
        ad = self._extract_ad(response)
        if ad is None:
            return
        item = self._build_listing_item(ad, response)
        self._log_detail_progress()
        yield item
        yield self._build_raw_item(ad, item)

    def _extract_ad(self, response) -> dict | None:
        next_data_raw = response.css("script#__NEXT_DATA__::text").get()
        if not next_data_raw:
            return None
        try:
            data = json.loads(next_data_raw)
        except json.JSONDecodeError:
            return None
        ad = data.get("props", {}).get("pageProps", {}).get("ad")
        if not ad:
            self.logger.warning("No ad data (soft 404?): %s", response.url)
        return ad or None

    def _build_listing_item(self, ad: dict, response) -> RawListingItem:
        photo_urls = [
            img.get("large", img.get("medium", ""))
            for img in ad.get("images", [])
            if img
        ]
        chars = {
            c["key"]: c["value"] for c in ad.get("characteristics", []) if "key" in c
        }
        features_str = str(ad.get("features", []))
        loc = ad.get("location", {}).get("address", {})
        coords = ad.get("location", {}).get("coordinates", {})
        raw_type = ((ad.get("target") or {}).get("ProperType") or "").lower()

        loader = ItemLoader(item=RawListingItem(), response=response)
        loader.default_output_processor = TakeFirst()

        loader.add_value("source_portal", "otodom")
        loader.add_value("source_url", response.url)
        loader.add_value("external_id", str(ad.get("id", "")))
        loader.add_value("title", ad.get("title", ""))
        loader.add_value("description", ad.get("description", ""))
        loader.add_value("city", self.city.capitalize() if self.city else None)
        loader.add_value("district", (loc.get("district") or {}).get("name"))
        loader.add_value("street", (loc.get("street") or {}).get("name"))
        loader.add_value("latitude", coords.get("latitude"))
        loader.add_value("longitude", coords.get("longitude"))
        loader.add_value("price_pln", self._extract_price(ad.get("totalPrice")))
        loader.add_value(
            "price_per_m2", self._extract_price(ad.get("pricePerSquareMeter"))
        )
        loader.add_value(
            "area_m2",
            self._safe_float(chars.get("m")) or ad.get("areaInSquareMeters"),
        )
        loader.add_value(
            "rooms",
            self._safe_int(chars.get("rooms_num")) or ad.get("roomsNumber"),
        )
        loader.add_value("floor", self._parse_floor(chars.get("floor_no")))
        loader.add_value(
            "total_floors", self._safe_int(chars.get("building_floors_num"))
        )
        loader.add_value("year_built", self._safe_int(chars.get("build_year")))
        loader.add_value("has_lift", chars.get("lift") == "yes")
        loader.add_value("has_balcony", "balcony" in features_str)
        loader.add_value("has_terrace", "terrace" in features_str)
        loader.add_value("has_storage", "basement" in features_str)
        loader.add_value("heating_type", chars.get("heating"))
        loader.add_value("parking", chars.get("parking"))
        loader.add_value("building_material", chars.get("building_material"))
        loader.add_value(
            "property_type",
            _PROPERTY_TYPE_MAP.get(raw_type, "to be checked" if raw_type else None),
        )
        loader.add_value("market_type", ad.get("market"))
        loader.add_value(
            "listing_type", "agency" if ad.get("agency") else "private"
        )
        loader.add_value("date_posted", ad.get("dateCreated"))
        loader.add_value("date_scraped", datetime.now(timezone.utc).isoformat())
        loader.add_value("photo_urls", photo_urls)
        loader.add_value("photo_count", len(photo_urls))
        loader.add_value("description_length", len(ad.get("description", "")))
        loader.add_value(
            "has_floor_plan",
            any(
                "plan" in (u or "").lower() or "rzut" in (u or "").lower()
                for u in photo_urls
            ),
        )
        loader.add_value("http_status", response.status)

        item = loader.load_item()
        item["photo_urls"] = photo_urls
        for field_name in item.fields:
            if field_name not in item:
                item[field_name] = None
        return item

    @staticmethod
    def _build_raw_item(ad: dict, listing_item: RawListingItem) -> RawJsonItem:
        raw_item = RawJsonItem()
        raw_item["external_id"] = listing_item.get("external_id")
        raw_item["source_url"] = listing_item.get("source_url")
        raw_item["raw_json"] = ad
        return raw_item

    def _log_detail_progress(self) -> None:
        self._detail_scraped += 1
        done, total = self._detail_scraped, self._detail_total
        step = max(25, total // 10)
        if done % step == 0 or done == total:
            self.logger.info(
                "Detail scrape: %d/%d pages done", done, total
            )

    def _on_detail_error(self, failure):
        self.logger.error(
            "Detail page request failed: %s — %s",
            failure.request.url,
            failure.value,
        )

    # ─── Static helpers ──────────────────────────────────────────

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
    def _safe_float(val):
        try:
            return float(val) if val else None
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_floor(floor_str: str | None) -> int | None:
        if not floor_str:
            return None
        if floor_str in ("ground_floor", "parter"):
            return 0
        try:
            return int(floor_str)
        except (ValueError, TypeError):
            return None

    def closed(self, reason):
        self._end_time = datetime.now(timezone.utc)
        if hasattr(self, "run_dir") and self.run_dir and self._start_time:
            try:
                detail_runs_file = self.run_dir / "detail_runs.jsonl"
                runtime_seconds = (self._end_time - self._start_time).total_seconds()
                completion_record = {
                    "run_id": self.run_timestamp,
                    "start_time": self._start_time.isoformat(timespec="seconds"),
                    "end_time": self._end_time.isoformat(timespec="seconds"),
                    "runtime_seconds": runtime_seconds,
                    "runtime_human": f"{runtime_seconds:.1f}s",
                    "city": self.city,
                    "slugs_requested": self._detail_total,
                    "items_scraped": self._detail_scraped,
                    "completion_reason": reason,
                    "record_type": "detail_run",
                }
                with open(detail_runs_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(completion_record) + "\n")
                self.logger.info(
                    "Detail spider completed in %.1f seconds (%d/%d items). Reason: %s",
                    runtime_seconds,
                    self._detail_scraped,
                    self._detail_total,
                    reason,
                )
            except OSError as e:
                self.logger.exception("Failed to write detail run record: %s", e)
