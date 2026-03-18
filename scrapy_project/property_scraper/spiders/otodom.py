import json
import scrapy
from datetime import datetime, timezone

from property_scraper.area_config import SearchArea, build_otodom_url
from property_scraper.items import RawListingItem


class OtodomSpider(scrapy.Spider):
    name = "otodom"
    allowed_domains = ["otodom.pl"]

    def __init__(
        self,
        city: str = "krakow",
        districts: str = "",
        price_min: str | None = None,
        price_max: str | None = None,
        max_pages: str = "20",
        **kwargs,
    ):
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
        next_data_raw = response.css("script#__NEXT_DATA__::text").get()
        if not next_data_raw:
            self.logger.warning("No __NEXT_DATA__ on %s", response.url)
            return
        try:
            data = json.loads(next_data_raw)
        except json.JSONDecodeError:
            self.logger.error("JSON decode failed: %s", response.url)
            return

        page_props = data.get("props", {}).get("pageProps", {})
        search_data = page_props.get("data", {}).get("searchAds", {})
        items = search_data.get("items", [])

        for listing in items:
            slug = listing.get("slug", "")
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
        next_data_raw = response.css("script#__NEXT_DATA__::text").get()
        if not next_data_raw:
            return
        try:
            data = json.loads(next_data_raw)
        except json.JSONDecodeError:
            return

        ad = data.get("props", {}).get("pageProps", {}).get("ad")
        if not ad:
            return  # soft 404 — listing removed or never existed

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
        item["has_floor_plan"] = any(
            "plan" in (u or "").lower() or "rzut" in (u or "").lower()
            for u in photo_urls
        )
        item["raw_json"] = ad
        yield item

    # ─── Helpers ─────────────────────────────────────────────────

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
    def _parse_floor(floor_str: str | None) -> int | None:
        if not floor_str:
            return None
        if floor_str in ("ground_floor", "parter"):
            return 0
        try:
            return int(floor_str)
        except (ValueError, TypeError):
            return None
