import scrapy
from scrapy import Field


class RawListingItem(scrapy.Item):
    # ─── Identity ────────────────────────────────────────────────
    source_portal = Field()       # "otodom" | "gratka" | "morizon"
    source_url = Field()
    external_id = Field()         # Portal's own listing ID
    listing_hash = Field()        # SHA-256 dedup fingerprint (set by pipeline)

    # ─── Headline ────────────────────────────────────────────────
    title = Field()
    description = Field()
    description_length = Field()

    # ─── Location ────────────────────────────────────────────────
    city = Field()
    district = Field()
    street = Field()
    latitude = Field()
    longitude = Field()

    # ─── Pricing ─────────────────────────────────────────────────
    price_pln = Field()
    price_per_m2 = Field()

    # ─── Physical attributes ──────────────────────────────────────
    area_m2 = Field()
    rooms = Field()
    floor = Field()
    total_floors = Field()
    year_built = Field()

    # ─── Features ────────────────────────────────────────────────
    has_lift = Field()
    has_balcony = Field()
    has_terrace = Field()
    has_storage = Field()
    has_floor_plan = Field()
    heating_type = Field()
    parking = Field()
    building_material = Field()

    # ─── Listing metadata ─────────────────────────────────────────
    market_type = Field()         # "primary" | "secondary"
    listing_type = Field()        # "agency" | "private"
    date_posted = Field()
    date_scraped = Field()

    # ─── Photos ──────────────────────────────────────────────────
    photo_urls = Field()          # list[str] — remote URLs
    photo_count = Field()
    photo_paths = Field()         # list[str] — MinIO object keys (set by pipeline)

    # ─── Raw data ────────────────────────────────────────────────
    raw_json = Field()            # Full source dict for debugging / re-parsing
