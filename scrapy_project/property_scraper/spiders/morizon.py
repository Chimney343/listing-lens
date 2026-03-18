import scrapy
from datetime import datetime, timezone

from property_scraper.area_config import SearchArea, build_morizon_url
from property_scraper.items import RawListingItem


class MorizonSpider(scrapy.Spider):
    name = "morizon"
    allowed_domains = ["morizon.pl"]

    # ─── CSS selectors (update here when site structure changes) ───────────
    # Search results page
    SEL_LISTING_LINKS = "a.property_link::attr(href)"

    # Detail page
    SEL_TITLE = "h1.single-offer__title::text"
    SEL_PRICE = "li.paramIconPrice strong::text"
    SEL_PRICE_PER_M2 = "li.paramIconPriceM2 strong::text"
    SEL_DESCRIPTION = "section.description__rolled-content p::text"
    SEL_DISTRICT = "p.single-offer__address a::text"
    SEL_STREET = "p.single-offer__address span.singleOfferInfoAddress::text"

    # Parameter table
    SEL_PARAM_LABEL = "p.moreDetails__definitionLabel::text"
    SEL_PARAM_VALUE = "p.moreDetails__definitionValue::text"

    SEL_PHOTO_URLS = "ul.gallery__slides img::attr(src)"

    # Soft-404 markers
    SOFT_404_TEXT = "Ogłoszenie wygasło"

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
        url = build_morizon_url(self.area, page=1)
        yield scrapy.Request(url, callback=self.parse_search, meta={"page": 1})

    def parse_search(self, response):
        links = response.css(self.SEL_LISTING_LINKS).getall()
        for link in links:
            yield scrapy.Request(
                response.urljoin(link),
                callback=self.parse_detail,
            )

        current_page = response.meta["page"]
        if links and current_page < self.area.max_pages:
            yield scrapy.Request(
                build_morizon_url(self.area, page=current_page + 1),
                callback=self.parse_search,
                meta={"page": current_page + 1},
            )

    def parse_detail(self, response):
        if self.SOFT_404_TEXT in response.text:
            self.logger.debug("Soft 404 (offer expired): %s", response.url)
            return

        params = dict(zip(
            [t.strip() for t in response.css(self.SEL_PARAM_LABEL).getall()],
            [t.strip() for t in response.css(self.SEL_PARAM_VALUE).getall()],
        ))

        photo_urls = response.css(self.SEL_PHOTO_URLS).getall()
        description = " ".join(response.css(self.SEL_DESCRIPTION).getall()).strip()

        title = response.css(self.SEL_TITLE).get("").strip()
        price_text = response.css(self.SEL_PRICE).get("").strip().replace("\xa0", "").replace(" ", "")
        price_per_m2_text = response.css(self.SEL_PRICE_PER_M2).get("").strip().replace("\xa0", "").replace(" ", "")

        address_parts = response.css(self.SEL_DISTRICT).getall()

        item = RawListingItem()
        item["source_portal"] = "morizon"
        item["source_url"] = response.url
        item["external_id"] = response.url.rstrip("/").split("-")[-1]
        item["title"] = title
        item["description"] = description
        item["description_length"] = len(description)
        item["city"] = "Kraków"
        item["district"] = address_parts[0].strip() if address_parts else None
        item["street"] = response.css(self.SEL_STREET).get("").strip() or None
        item["latitude"] = None
        item["longitude"] = None

        item["price_pln"] = self._parse_float(price_text.replace("zł", "").replace("PLN", ""))
        item["price_per_m2"] = self._parse_float(price_per_m2_text.replace("zł/m²", "").replace("zł/m2", ""))

        item["area_m2"] = self._parse_float(params.get("Powierzchnia", "").replace("m²", "").replace("m2", ""))
        item["rooms"] = self._safe_int(params.get("Liczba pokoi"))
        item["floor"] = self._parse_floor(params.get("Piętro"))
        item["total_floors"] = self._safe_int(params.get("Liczba pięter"))
        item["year_built"] = self._safe_int(params.get("Rok budowy"))

        item["has_lift"] = "winda" in response.text.lower()
        item["has_balcony"] = "balkon" in response.text.lower()
        item["has_terrace"] = "taras" in response.text.lower()
        item["has_storage"] = "piwnica" in response.text.lower() or "komórka" in response.text.lower()
        item["heating_type"] = params.get("Ogrzewanie")
        item["parking"] = params.get("Garaż / miejsce parkingowe") or params.get("Parking")
        item["building_material"] = params.get("Materiał budynku")

        item["market_type"] = params.get("Rynek")
        item["listing_type"] = None
        item["date_posted"] = params.get("Dodane")
        item["date_scraped"] = datetime.now(timezone.utc).isoformat()

        item["photo_urls"] = photo_urls
        item["photo_count"] = len(photo_urls)
        item["has_floor_plan"] = any(
            "plan" in (u or "").lower() or "rzut" in (u or "").lower()
            for u in photo_urls
        )
        item["raw_json"] = params
        yield item

    # ─── Helpers ─────────────────────────────────────────────────

    @staticmethod
    def _parse_float(val: str | None) -> float | None:
        if not val:
            return None
        cleaned = val.strip().replace(",", ".").replace(" ", "")
        try:
            return float(cleaned)
        except ValueError:
            return None

    @staticmethod
    def _safe_int(val) -> int | None:
        try:
            return int(val) if val else None
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_floor(floor_str: str | None) -> int | None:
        if not floor_str:
            return None
        floor_str = floor_str.strip().lower()
        if floor_str in ("parter", "0"):
            return 0
        try:
            return int(floor_str)
        except (ValueError, TypeError):
            return None
