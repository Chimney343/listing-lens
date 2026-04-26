"""Helpers for slug queue handoff into PostgreSQL."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

try:
    import psycopg
except ImportError:  # pragma: no cover - exercised only when dependency is missing
    psycopg = None  # type: ignore[assignment]

def connect(database_url: str):
    """Create a synchronous psycopg connection."""

    if psycopg is None or not hasattr(psycopg, "connect"):
        raise RuntimeError("psycopg is required to connect to PostgreSQL")
    return psycopg.connect(database_url)

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