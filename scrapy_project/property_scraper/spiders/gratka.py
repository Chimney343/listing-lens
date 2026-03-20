import scrapy
from datetime import datetime, timezone

from property_scraper.area_config import SearchArea, build_gratka_url
from property_scraper.items import RawListingItem

_PROPERTY_TYPE_MAP = {"mieszkanie": "apartment", "dom": "house"}


class GratkaSpider(scrapy.Spider):
    name = "gratka"
    allowed_domains = ["gratka.pl"]

    # ─── CSS selectors (update here when site structure changes) ───────────
    # Search results page
    SEL_LISTING_LINKS = "article.offer-item a.offer-item__title::attr(href)"

    # Detail page
    SEL_TITLE = "h1.sticker__title::text"
    SEL_PRICE = "span.priceInfo__value::text"
    SEL_PRICE_PER_M2 = "span.priceInfo__additional::text"
    SEL_DESCRIPTION = "div.description__rolled-content *::text"
    SEL_DISTRICT = "address.offer-address span::text"
    SEL_STREET = "address.offer-address a::text"

    # Key-value attribute table on detail page
    SEL_PARAM_LABEL = "li.parameters__item span.parameters__label::text"
    SEL_PARAM_VALUE = "li.parameters__item strong.parameters__value::text"

    SEL_PHOTO_URLS = "div.swiper-slide img::attr(src)"

    # Soft-404 markers
    SOFT_404_TEXT = "Oferta nieaktualna"

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
        raise NotImplementedError("GratkaSpider is not implemented yet")

    def parse_search(self, response):
        raise NotImplementedError("GratkaSpider is not implemented yet")

    def parse_detail(self, response):
        raise NotImplementedError("GratkaSpider is not implemented yet")
