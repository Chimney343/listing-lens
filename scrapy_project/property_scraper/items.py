import scrapy
from scrapy import Field
from itemloaders.processors import Identity


class RawJsonItem(scrapy.Item):
    """Holds the full raw API dict for a listing.  Written to raw_output.jsonl.

    To graduate a field to RawListingItem:
      1. Add the field to RawListingItem below.
      2. Extract the value here and add a loader.add_value() call in parse_detail.
      3. Remove it from the raw_json dict if desired (or leave it — duplication is fine).
    """
    external_id = Field()   # links back to RawListingItem
    source_url  = Field()
    raw_json    = Field()   # the full ad dict straight from __NEXT_DATA__
class SlugRunMetaItem(scrapy.Item):
    """Run metadata written once in closed(). Matches the slug_runs table."""

    run_id = Field()
    portal = Field()
    city = Field()
    started_at = Field()
    ended_at = Field()
    runtime_seconds = Field()
    completion_reason = Field()
    parameters = Field()
    total_advertised = Field()
    investments_found = Field()
    slug_count = Field()


class SlugCollectionItem(scrapy.Item):
    """Spider-populated fields for a raw_slugs row, yielded once per discovered slug."""

    id = Field()          # UUID assigned at collection time
    run_id = Field()
    portal = Field()
    slug = Field()
    full_url = Field()
    observed_at = Field()  # ISO-8601 UTC timestamp of this observation


class RawListingItem(scrapy.Item):
    # ─── Identity ────────────────────────────────────────────────
    source_portal = Field()       # "otodom" | "gratka" | "morizon"
    source_url = Field()
    external_id = Field()         # Portal's own listing ID

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
    property_type = Field()       # "mieszkanie" | "dom" | etc.
    market_type = Field()         # "primary" | "secondary"
    listing_type = Field()        # "agency" | "private"
    date_posted = Field()
    date_scraped = Field()

    # ─── Photos ──────────────────────────────────────────────────
    photo_urls = Field(output_processor=Identity())  # list[str] — remote URLs
    photo_count = Field()
    photo_paths = Field()         # list[str] — MinIO object keys (set by pipeline)

    # ─── Scraping metadata ───────────────────────────────────────
    http_status = Field()            # HTTP status code of the detail page (200, 404, etc.)

    # ─── Raw data ────────────────────────────────────────────────
    # raw_json lives in RawJsonItem (written to raw_output.jsonl) — not here.
