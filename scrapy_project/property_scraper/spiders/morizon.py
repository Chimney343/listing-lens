import scrapy
from datetime import datetime, timezone

from property_scraper.area_config import SearchArea, build_morizon_url
from property_scraper.items import RawListingItem

_PROPERTY_TYPE_MAP = {"mieszkanie": "apartment", "dom": "house"}


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
        city: str = "mielec",
        property_type: str = "mieszkanie",
        districts: str = "",
        price_min: str | None = None,
        price_max: str | None = None,
        max_pages: str = "20",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.area = SearchArea(
            city=city,
            property_type=property_type,
            districts=[d.strip() for d in districts.split(",") if d.strip()],
            price_min=int(price_min) if price_min else None,
            price_max=int(price_max) if price_max else None,
            max_pages=int(max_pages),
        )

    async def start(self):
        raise NotImplementedError("MorizonSpider is not implemented yet")

    def parse_search(self, response):
        raise NotImplementedError("MorizonSpider is not implemented yet")

    def parse_detail(self, response):
        raise NotImplementedError("MorizonSpider is not implemented yet")
