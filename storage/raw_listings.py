"""Helpers for append-only raw listing ingest into PostgreSQL."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any


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


def build_raw_listing_record(item: Mapping[str, Any]) -> dict[str, Any]:
    """Map a RawListingItem into the columns stored on raw_listings.

    raw_listings is the append-only ingest table. Every field from the spider
    is stored verbatim with only light type normalization.
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