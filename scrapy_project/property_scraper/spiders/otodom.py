import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import scrapy
from scrapy_playwright.page import PageMethod

from property_scraper.area_config import SearchArea, build_otodom_url
from property_scraper.items import RawListingItem

_STEALTH_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    window.chrome = {runtime: {}};
    Object.defineProperty(navigator, 'languages', {get: () => ['pl-PL', 'pl', 'en-US', 'en']});
    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
"""


async def _page_init(page, request):
    await page.add_init_script(_STEALTH_SCRIPT)


def _pw_meta(wait_networkidle: bool = True) -> dict:
    methods = [PageMethod("wait_for_load_state", "networkidle", timeout=30_000)] if wait_networkidle else []
    return {
        "playwright": True,
        "playwright_context": "default",
        "playwright_page_init_callback": _page_init,
        "playwright_page_methods": methods,
    }


_PROPERTY_TYPE_MAP = {"mieszkanie": "apartment", "dom": "house"}

# GraphQL persisted-query hash for fetching investment unit listings.
_PAGINATED_UNITS_HASH = "ddc9f328a32057395caf18ef667d3ee4242ea57e73481cc8a56ee9618d0c2b31"
_UNITS_API_PAGE_SIZE = 200  # API accepts at least 200


def _build_units_api_url(ad_id: int, page: int = 1) -> str:
    """Build the /api/query URL for PaginatedInvestmentUnits."""
    variables = json.dumps({
        "id": ad_id,
        "lookup": {
            "filters": {"numberOfRooms": []},
            "page": page,
            "pageSize": _UNITS_API_PAGE_SIZE,
            "sort": {"by": "Price", "direction": "asc"},
            "withFacets": True,
        },
    }, separators=(",", ":"))
    extensions = json.dumps({
        "persistedQuery": {
            "sha256Hash": _PAGINATED_UNITS_HASH,
            "version": 1,
        },
    }, separators=(",", ":"))
    return (
        "https://www.otodom.pl/api/query?"
        + urlencode({
            "operationName": "PaginatedInvestmentUnits",
            "variables": variables,
            "extensions": extensions,
        })
    )


class OtodomSpider(scrapy.Spider):
    name = "otodom"
    allowed_domains = ["otodom.pl"]

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
        max_pages: str = "20",
        phase1_only: str = "0",
        slug: str | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.phase1_only = phase1_only.strip() not in ("0", "false", "")
        self.single_slug = slug
        self.area = SearchArea(
            city=city,
            voivodeship=voivodeship,
            powiat=powiat,
            gmina=gmina,
            property_type=property_type,
            districts=[d.strip() for d in districts.split(",") if d.strip()],
            price_min=int(price_min) if price_min else None,
            price_max=int(price_max) if price_max else None,
            max_pages=int(max_pages),
        )

    # ─── Phase 1: collect slugs from all search pages ────────────

    async def start(self):
        if self.single_slug:
            yield scrapy.Request(
                f"https://www.otodom.pl/pl/oferta/{self.single_slug}",
                callback=self.parse_detail,
                errback=self._on_detail_error,
                meta=_pw_meta(),
            )
            return
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
        self._total_pages: int = min(total_pages, self.area.max_pages)
        self._slugs: set[str] = set()
        self._investments: dict[int, tuple[str, int]] = {}  # ad_id → (slug, expected_units)
        self._search_pages_received: int = 0

        self.logger.info(
            "Bootstrap: API reports %d items across %d pages (capped at %d)",
            self._total_items, total_pages, self._total_pages,
        )

        self._absorb_search_items(search_data, page=1)

        for page in range(2, self._total_pages + 1):
            yield scrapy.Request(
                build_otodom_url(self.area, page=page),
                callback=self._collect_slugs,
                errback=self._on_search_error,
                meta={"page": page, **_pw_meta()},
            )

        if self._total_pages == 1:
            yield from self._finish_search_collection()

    def _collect_slugs(self, response):
        """Collect slugs from a follow-up search page; trigger next phase when done."""
        search_data = self._parse_search_data(response)
        if search_data is None:
            self._search_pages_received += 1
        else:
            self._absorb_search_items(search_data, page=response.meta["page"])

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
                    expected = item.get("investmentUnitsNumber", 0)
                    self._investments[ad_id] = (slug, expected)
                    self.logger.info(
                        "  Investment detected: %s (id=%s, %d units)",
                        slug, ad_id, expected,
                    )
            else:
                self._slugs.add(slug)
        added = len(self._slugs) - before
        self._search_pages_received += 1
        self.logger.info(
            "Search page %d/%d — %d new listing slugs (running total: %d listings, %d investments)",
            page, self._total_pages, added, len(self._slugs), len(self._investments),
        )

    # ─── Phase 1.5: expand investments into unit slugs ───────────

    def _finish_search_collection(self):
        """After all search pages collected, expand investments or go straight to Phase 2."""
        listing_count = len(self._slugs)
        investment_count = len(self._investments)
        self.logger.info(
            "Search complete: %d listing slugs + %d investments",
            listing_count, investment_count,
        )

        if investment_count > 0:
            # Track how many investment API responses we're waiting for
            self._investment_responses_pending = investment_count
            for ad_id, (inv_slug, expected_units) in self._investments.items():
                self.logger.info(
                    "Phase 1.5: fetching unit slugs for investment %s (id=%d, %d expected)",
                    inv_slug, ad_id, expected_units,
                )
                yield scrapy.Request(
                    _build_units_api_url(ad_id),
                    callback=self._parse_investment_units,
                    errback=self._on_investment_error,
                    meta={
                        "ad_id": ad_id, "inv_slug": inv_slug,
                        "expected_units": expected_units, **_pw_meta(),
                    },
                )
        else:
            yield from self._finish_all_collection()

    def _parse_investment_units(self, response):
        """Parse GraphQL PaginatedInvestmentUnits response and collect unit slugs."""
        ad_id = response.meta["ad_id"]
        inv_slug = response.meta["inv_slug"]
        expected_units = response.meta["expected_units"]

        try:
            raw = response.css("pre::text").get() or response.text
            jdata = json.loads(raw)
        except (json.JSONDecodeError, Exception) as e:
            self.logger.error(
                "Failed to parse investment units API for %s (id=%d): %s",
                inv_slug, ad_id, e,
            )
            self._investment_responses_pending -= 1
            if self._investment_responses_pending == 0:
                yield from self._finish_all_collection()
            return

        paginated = jdata.get("data", {}).get("paginatedUnits", {})
        items = paginated.get("items", [])
        pagination = paginated.get("pagination", {})
        total_results = pagination.get("totalResults", 0)
        total_pages = pagination.get("totalPages", 1)

        if expected_units and total_results != expected_units:
            self.logger.warning(
                "Investment %s: search advertised %d units but API reports %d",
                inv_slug, expected_units, total_results,
            )

        unit_slugs = set()
        for unit in items:
            url = unit.get("url", "")
            if url:
                unit_slugs.add(url.rstrip("/").split("/")[-1])

        # Store parent slug too — validation pipeline decides what to do with it
        self._slugs.add(inv_slug)
        self._slugs.update(unit_slugs)
        self.logger.info(
            "Investment %s: collected %d/%d unit slugs (total slugs now: %d)",
            inv_slug, len(unit_slugs), total_results, len(self._slugs),
        )

        # If >200 units exist, schedule extra pages and track them in pending counter
        extra_pages = total_pages - 1 if len(items) < total_results and total_pages > 1 else 0
        self._investment_responses_pending += extra_pages
        for pg in range(2, total_pages + 1):
            yield scrapy.Request(
                _build_units_api_url(ad_id, page=pg),
                callback=self._parse_investment_units_extra,
                errback=self._on_investment_error,
                meta={"ad_id": ad_id, "inv_slug": inv_slug, **_pw_meta()},
            )

        self._investment_responses_pending -= 1
        if self._investment_responses_pending == 0:
            yield from self._finish_all_collection()

    def _parse_investment_units_extra(self, response):
        """Handle additional pages of investment units (for >200 unit investments)."""
        try:
            raw = response.css("pre::text").get() or response.text
            jdata = json.loads(raw)
        except Exception:
            self._investment_responses_pending -= 1
            if self._investment_responses_pending == 0:
                yield from self._finish_all_collection()
            return

        items = jdata.get("data", {}).get("paginatedUnits", {}).get("items", [])
        for unit in items:
            url = unit.get("url", "")
            if url:
                self._slugs.add(url.rstrip("/").split("/")[-1])

        self._investment_responses_pending -= 1
        if self._investment_responses_pending == 0:
            yield from self._finish_all_collection()

    # ─── Error handlers ──────────────────────────────────────────

    def _on_search_error(self, failure):
        """Handle failed search page request."""
        self.logger.error("Search page request failed: %s", failure.value)
        self._search_pages_received += 1
        if self._search_pages_received == self._total_pages:
            yield from self._finish_search_collection()

    def _on_investment_error(self, failure):
        """Handle failed investment API request."""
        self.logger.error("Investment API request failed: %s", failure.value)
        self._investment_responses_pending -= 1
        if self._investment_responses_pending == 0:
            yield from self._finish_all_collection()

    def _on_detail_error(self, failure):
        """Handle failed detail page request."""
        self.logger.error(
            "Detail page request failed: %s — %s",
            failure.request.url, failure.value,
        )

    # ─── Phase 2: scrape detail pages ────────────────────────────

    def _persist_slug_run(self) -> None:
        """Write slug run record to data/slug_runs.jsonl."""
        data_dir = Path(self.settings.get("DATA_DIR"))
        data_dir.mkdir(parents=True, exist_ok=True)
        slug_runs_file = data_dir / "slug_runs.jsonl"

        collected = len(self._slugs)
        investment_count = len(self._investments)
        record = {
            "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "city": self.area.city,
            "total_advertised": self._total_items,
            "investments_found": investment_count,
            "investment_slugs": {
                str(k): {"slug": slug, "expected_units": units}
                for k, (slug, units) in self._investments.items()
            },
            "slug_count": collected,
            "slugs": sorted(self._slugs),
        }
        with open(slug_runs_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

        self.logger.info(
            "Final slug set: %d total (%d from search + expanded from %d investments). "
            "Saved to %s",
            collected, collected - investment_count, investment_count, slug_runs_file,
        )

    def _finish_all_collection(self):
        """All slugs collected. Persist and start Phase 2."""
        self._persist_slug_run()

        if self.phase1_only:
            self.logger.info("phase1_only=1 — skipping Phase 2 detail scrape")
            return

        collected = len(self._slugs)
        self.logger.info("Phase 2: fetching %d detail pages", collected)
        for slug in self._slugs:
            yield scrapy.Request(
                f"https://www.otodom.pl/pl/oferta/{slug}",
                callback=self.parse_detail,
                errback=self._on_detail_error,
                meta=_pw_meta(),
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

    # ─── Phase 2 detail parser ───────────────────────────────────

    def parse_detail(self, response):
        next_data_raw = response.css("script#__NEXT_DATA__::text").get()
        if not next_data_raw:
            return
        try:
            data = json.loads(next_data_raw)
        except json.JSONDecodeError:
            return

        ad = data.get("props", {}).get("pageProps", {}).get("ad")
        if not ad:
            self.logger.warning("No ad data (soft 404?): %s", response.url)
            return

        images = ad.get("images", [])
        photo_urls = [
            img.get("large", img.get("medium", ""))
            for img in images
            if img
        ]
        chars = {
            c["key"]: c["value"]
            for c in ad.get("characteristics", [])
            if "key" in c
        }
        features_str = str(ad.get("features", []))

        item = RawListingItem()
        item["source_portal"] = "otodom"
        item["source_url"] = response.url
        item["external_id"] = str(ad.get("id", ""))
        item["title"] = ad.get("title", "")
        item["description"] = ad.get("description", "")
        item["city"] = self.area.city.capitalize()

        loc = ad.get("location", {}).get("address", {})
        item["district"] = (loc.get("district") or {}).get("name")
        item["street"] = (loc.get("street") or {}).get("name")

        coords = ad.get("location", {}).get("coordinates", {})
        item["latitude"] = coords.get("latitude")
        item["longitude"] = coords.get("longitude")

        item["price_pln"] = self._extract_price(ad.get("totalPrice"))
        item["price_per_m2"] = self._extract_price(ad.get("pricePerSquareMeter"))
        item["area_m2"] = self._safe_float(chars.get("m")) or ad.get("areaInSquareMeters")
        item["rooms"] = self._safe_int(chars.get("rooms_num")) or ad.get("roomsNumber")
        item["floor"] = self._parse_floor(chars.get("floor_no"))
        item["total_floors"] = self._safe_int(chars.get("building_floors_num"))
        item["year_built"] = self._safe_int(chars.get("build_year"))

        item["has_lift"] = chars.get("lift") == "yes"
        item["has_balcony"] = "balcony" in features_str
        item["has_terrace"] = "terrace" in features_str
        item["has_storage"] = "basement" in features_str
        item["heating_type"] = chars.get("heating")
        item["parking"] = chars.get("parking")
        item["building_material"] = chars.get("building_material")

        raw_type = ((ad.get("target") or {}).get("ProperType") or "").lower()
        item["property_type"] = _PROPERTY_TYPE_MAP.get(raw_type, "to be checked" if raw_type else None)
        item["market_type"] = ad.get("market")
        item["listing_type"] = "agency" if ad.get("agency") else "private"
        item["date_posted"] = ad.get("dateCreated")
        item["date_scraped"] = datetime.now(timezone.utc).isoformat()

        item["photo_urls"] = photo_urls
        item["photo_count"] = len(photo_urls)
        item["description_length"] = len(item["description"])
        item["has_floor_plan"] = any(
            "plan" in (u or "").lower() or "rzut" in (u or "").lower()
            for u in photo_urls
        )
        item["raw_json"] = ad
        yield item

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
