"""Helpers for the PostgreSQL-backed storage layer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

try:
    import psycopg
except ImportError:  # pragma: no cover - exercised only when dependency is missing
    psycopg = None  # type: ignore[assignment]


LISTING_COLUMNS = (
    "source_portal",
    "source_url",
    "external_id",
    "title",
    "description",
    "city",
    "district",
    "street",
    "latitude",
    "longitude",
    "area_m2",
    "rooms",
    "floor",
    "total_floors",
    "year_built",
    "property_type",
    "market_type",
    "listing_type",
    "heating_type",
    "building_material",
    "has_lift",
    "has_balcony",
    "has_terrace",
    "has_parking",
    "has_storage",
    "photo_count",
    "photo_paths",
    "composite_score",
    "status",
    "last_scraped_at",
    "last_scored_at",
)

LISTING_INSERT_SQL = f"""
INSERT INTO listings ({", ".join(LISTING_COLUMNS)})
VALUES ({", ".join(["%s"] * len(LISTING_COLUMNS))})
ON CONFLICT (source_url) DO UPDATE SET
    source_portal = EXCLUDED.source_portal,
    external_id = EXCLUDED.external_id,
    title = EXCLUDED.title,
    description = EXCLUDED.description,
    city = EXCLUDED.city,
    district = EXCLUDED.district,
    street = EXCLUDED.street,
    latitude = EXCLUDED.latitude,
    longitude = EXCLUDED.longitude,
    area_m2 = EXCLUDED.area_m2,
    rooms = EXCLUDED.rooms,
    floor = EXCLUDED.floor,
    total_floors = EXCLUDED.total_floors,
    year_built = EXCLUDED.year_built,
    property_type = EXCLUDED.property_type,
    market_type = EXCLUDED.market_type,
    listing_type = EXCLUDED.listing_type,
    heating_type = EXCLUDED.heating_type,
    building_material = EXCLUDED.building_material,
    has_lift = EXCLUDED.has_lift,
    has_balcony = EXCLUDED.has_balcony,
    has_terrace = EXCLUDED.has_terrace,
    has_parking = EXCLUDED.has_parking,
    has_storage = EXCLUDED.has_storage,
    photo_count = EXCLUDED.photo_count,
    photo_paths = EXCLUDED.photo_paths,
    composite_score = EXCLUDED.composite_score,
    status = EXCLUDED.status,
    last_scraped_at = EXCLUDED.last_scraped_at,
    last_scored_at = EXCLUDED.last_scored_at,
    updated_at = now()
RETURNING id
""".strip()

PRICE_LOOKUP_SQL = """
SELECT price_pln
FROM price_history
WHERE listing_id = %s
ORDER BY observed_at DESC
LIMIT 1
""".strip()

PRICE_INSERT_SQL = """
INSERT INTO price_history (listing_id, price_pln, price_per_m2, observed_at, source)
VALUES (%s, %s, %s, %s, %s)
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


def build_listing_record(item: Mapping[str, Any]) -> dict[str, Any]:
    """Map a RawListingItem into the columns stored on listings."""

    parking_value = item.get("has_parking")
    if parking_value is None:
        parking_value = item.get("parking")

    return {
        "source_portal": item.get("source_portal"),
        "source_url": item.get("source_url"),
        "external_id": item.get("external_id"),
        "title": item.get("title"),
        "description": item.get("description"),
        "city": item.get("city"),
        "district": item.get("district"),
        "street": item.get("street"),
        "latitude": item.get("latitude"),
        "longitude": item.get("longitude"),
        "area_m2": item.get("area_m2"),
        "rooms": item.get("rooms"),
        "floor": item.get("floor"),
        "total_floors": item.get("total_floors"),
        "year_built": item.get("year_built"),
        "property_type": _normalize_text(item.get("property_type")),
        "market_type": _normalize_text(item.get("market_type"), upper=True),
        "listing_type": _normalize_text(item.get("listing_type")),
        "heating_type": item.get("heating_type"),
        "building_material": item.get("building_material"),
        "has_lift": _optional_bool(item.get("has_lift")),
        "has_balcony": _optional_bool(item.get("has_balcony")),
        "has_terrace": _optional_bool(item.get("has_terrace")),
        "has_parking": _optional_bool(parking_value),
        "has_storage": _optional_bool(item.get("has_storage")),
        "photo_count": item.get("photo_count") or 0,
        "photo_paths": _to_text_list(item.get("photo_paths")),
        "composite_score": item.get("composite_score"),
        "status": _normalize_text(item.get("status") or "active"),
        "last_scraped_at": _to_datetime(item.get("date_scraped")),
        "last_scored_at": item.get("last_scored_at"),
    }


def build_price_record(
    listing_id: Any,
    item: Mapping[str, Any],
    observed_at: datetime,
) -> dict[str, Any]:
    """Build the append-only price_history row for a listing."""

    return {
        "listing_id": listing_id,
        "price_pln": item.get("price_pln"),
        "price_per_m2": item.get("price_per_m2"),
        "observed_at": observed_at,
        "source": "scrape",
    }


def has_price_changed(new_price: Any, previous_price: Any) -> bool:
    """Return True when a listing needs a new price_history row."""

    if new_price is None:
        return False
    if previous_price is None:
        return True
    return new_price != previous_price