"""Helpers for the PostgreSQL-backed storage layer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

try:
    import psycopg
except ImportError:  # pragma: no cover - exercised only when dependency is missing
    psycopg = None  # type: ignore[assignment]


RAW_LISTING_COLUMNS = (
    "source_portal",
    "source_url",
    "external_id",
    "title",
    "description",
    "description_length",
    "city",
    "district",
    "street",
    "latitude",
    "longitude",
    "price_pln",
    "price_per_m2",
    "area_m2",
    "rooms",
    "floor",
    "total_floors",
    "year_built",
    "has_lift",
    "has_balcony",
    "has_terrace",
    "has_storage",
    "has_floor_plan",
    "heating_type",
    "parking",
    "has_parking",
    "building_material",
    "property_type",
    "market_type",
    "listing_type",
    "date_posted",
    "photo_urls",
    "photo_count",
    "photo_paths",
    "http_status",
    "scraped_at",
)

RAW_LISTING_INSERT_SQL = f"""
INSERT INTO raw_listings ({", ".join(RAW_LISTING_COLUMNS)})
VALUES ({", ".join(["%s"] * len(RAW_LISTING_COLUMNS))})
RETURNING id
""".strip()


def connect(database_url: str):
    """Create a synchronous psycopg connection."""

    if psycopg is None or not hasattr(psycopg, "connect"):
        raise RuntimeError("psycopg is required to connect to PostgreSQL")
    return psycopg.connect(database_url)


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _normalize_text(value: Any, *, upper: bool = False) -> Any:
    if not isinstance(value, str):
        return value
    return value.upper() if upper else value.lower()


def _to_optional_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    return _to_datetime(value)


# ── raw_slugs ──────────────────────────────────────────────────────────────

RAW_SLUG_COLUMNS = (
    "id",
    "run_id",
    "portal",
    "slug",
    "full_url",
    "observed_at",
)

RAW_SLUG_INSERT_SQL = f"""
INSERT INTO raw_slugs ({", ".join(RAW_SLUG_COLUMNS)})
VALUES ({", ".join(["%s"] * len(RAW_SLUG_COLUMNS))})
ON CONFLICT DO NOTHING
""".strip()


def build_raw_slug_record(item: Mapping[str, Any]) -> dict[str, Any]:
    """Map a SlugCollectionItem into the columns stored on raw_slugs."""
    return {
        "id": item.get("id"),
        "run_id": item.get("run_id"),
        "portal": item.get("portal"),
        "slug": item.get("slug"),
        "full_url": item.get("full_url"),
        "observed_at": _to_datetime(item.get("observed_at")),
    }


# ── slug_runs ─────────────────────────────────────────────────────────────

SLUG_RUN_COLUMNS = (
    "run_id",
    "portal",
    "city",
    "started_at",
    "ended_at",
    "runtime_seconds",
    "completion_reason",
    "parameters",
    "total_advertised",
    "investments_found",
    "slug_count",
)

SLUG_RUN_INSERT_SQL = f"""
INSERT INTO slug_runs ({", ".join(SLUG_RUN_COLUMNS)})
VALUES ({", ".join(["%s"] * len(SLUG_RUN_COLUMNS))})
ON CONFLICT (run_id) DO NOTHING
""".strip()


def build_slug_run_record(item: Mapping[str, Any]) -> dict[str, Any]:
    """Map a SlugRunMetaItem into the columns stored on slug_runs."""
    parameters = item.get("parameters") or {}
    return {
        "run_id": item.get("run_id"),
        "portal": item.get("portal"),
        "city": item.get("city") or "",
        "started_at": _to_datetime(item.get("started_at")),
        "ended_at": _to_optional_datetime(item.get("ended_at")),
        "runtime_seconds": item.get("runtime_seconds"),
        "completion_reason": item.get("completion_reason"),
        "parameters": parameters,
        "total_advertised": item.get("total_advertised"),
        "investments_found": item.get("investments_found"),
        "slug_count": item.get("slug_count") or 0,
    }


# ── slug queue refresh ────────────────────────────────────────────────────

_REFRESH_SLUG_QUEUE_SQL = """
INSERT INTO slugs (portal, slug, full_url, first_seen_at, last_seen_at, observation_count)
SELECT
    portal,
    slug,
    full_url,
    MIN(observed_at) AS first_seen_at,
    MAX(observed_at) AS last_seen_at,
    COUNT(*)         AS observation_count
FROM raw_slugs
GROUP BY portal, slug, full_url
ON CONFLICT (full_url) DO UPDATE SET
    last_seen_at      = EXCLUDED.last_seen_at,
    observation_count = EXCLUDED.observation_count,
    scrape_status     = CASE
        WHEN slugs.scrape_status = 'scraped'
             AND slugs.last_scraped_at < EXCLUDED.last_seen_at
        THEN 'pending'
        ELSE slugs.scrape_status
    END
"""


def refresh_slug_queue(conn) -> int:
    """Upsert the operational ``slugs`` queue from the ``raw_slugs`` log.

    Safe to call at any time and any frequency — fully idempotent.
    Slugs previously marked ``'scraped'`` are re-queued as ``'pending'``
    when a newer observation arrives after the last scrape.

    Returns the number of rows inserted or updated.
    """
    with conn.transaction():
        with conn.cursor() as cursor:
            cursor.execute(_REFRESH_SLUG_QUEUE_SQL)
            return cursor.rowcount


def _to_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise TypeError(f"Unsupported datetime value: {value!r}")


def _to_text_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [str(entry) for entry in value if entry not in (None, "")]
    return [str(value)]


def build_raw_listing_record(item: Mapping[str, Any]) -> dict[str, Any]:
    """Map a RawListingItem into the columns stored on raw_listings.

    raw_listings is the append-only ingest table.  Every field from the spider
    is stored verbatim — no deduplication, no price-change logic.  That work
    belongs to ListingProcessor (Stage 2).
    """
    parking_value = item.get("has_parking")
    if parking_value is None:
        parking_value = item.get("parking")

    return {
        "source_portal": item.get("source_portal"),
        "source_url": item.get("source_url"),
        "external_id": item.get("external_id"),
        "title": item.get("title"),
        "description": item.get("description"),
        "description_length": item.get("description_length"),
        "city": item.get("city"),
        "district": item.get("district"),
        "street": item.get("street"),
        "latitude": item.get("latitude"),
        "longitude": item.get("longitude"),
        "price_pln": item.get("price_pln"),
        "price_per_m2": item.get("price_per_m2"),
        "area_m2": item.get("area_m2"),
        "rooms": item.get("rooms"),
        "floor": item.get("floor"),
        "total_floors": item.get("total_floors"),
        "year_built": item.get("year_built"),
        "has_lift": _optional_bool(item.get("has_lift")),
        "has_balcony": _optional_bool(item.get("has_balcony")),
        "has_terrace": _optional_bool(item.get("has_terrace")),
        "has_storage": _optional_bool(item.get("has_storage")),
        "has_floor_plan": _optional_bool(item.get("has_floor_plan")),
        "heating_type": item.get("heating_type"),
        "parking": item.get("parking"),
        "has_parking": _optional_bool(parking_value),
        "building_material": item.get("building_material"),
        "property_type": _normalize_text(item.get("property_type")),
        "market_type": _normalize_text(item.get("market_type"), upper=True),
        "listing_type": _normalize_text(item.get("listing_type")),
        "date_posted": item.get("date_posted"),
        "photo_urls": _to_text_list(item.get("photo_urls")),
        "photo_count": item.get("photo_count") or 0,
        "photo_paths": _to_text_list(item.get("photo_paths")),
        "http_status": item.get("http_status"),
        "scraped_at": _to_datetime(item.get("date_scraped")),
    }