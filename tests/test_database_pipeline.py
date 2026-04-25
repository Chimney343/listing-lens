"""Tests for the PostgreSQL-backed Scrapy pipeline."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from scrapy.exceptions import DropItem, NotConfigured

from storage import db as storage
from property_scraper.items import RawListingItem, SlugCollectionItem
from property_scraper.pipelines import DatabasePipeline


class FakeCursor:
    def __init__(self, fetchone_results):
        self.fetchone_results = list(fetchone_results)
        self.executed = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        if self.fetchone_results:
            return self.fetchone_results.pop(0)
        return None


class FakeTransaction:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        self.connection.transaction_count += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        self.connection.transaction_exits.append(
            exc_type.__name__ if exc_type is not None else None
        )
        return False


class FakeConnection:
    def __init__(self, fetchone_results):
        self.cursor_obj = FakeCursor(fetchone_results)
        self.closed = False
        self.transaction_count = 0
        self.transaction_exits = []

    def cursor(self):
        return self.cursor_obj

    def transaction(self):
        return FakeTransaction(self)

    def close(self):
        self.closed = True


class FakeSettings:
    def __init__(self, *, use_db_slug_queue: bool, database_url: str | None) -> None:
        self._use_db_slug_queue = use_db_slug_queue
        self._database_url = database_url

    def getbool(self, key: str, default: bool = False) -> bool:
        if key == "USE_DB_SLUG_QUEUE":
            return self._use_db_slug_queue
        return default

    def get(self, key: str, default=None):
        if key == "DATABASE_URL":
            return self._database_url
        return default


def _make_crawler(*, use_db_slug_queue: bool, database_url: str | None):
    return SimpleNamespace(
        settings=FakeSettings(
            use_db_slug_queue=use_db_slug_queue,
            database_url=database_url,
        )
    )


def _build_item(**overrides):
    item = RawListingItem()
    item.update(
        {
            "source_portal": "otodom",
            "source_url": "https://www.otodom.pl/pl/oferta/test-123",
            "external_id": "123",
            "title": "Przykładowe mieszkanie",
            "description": "Opis",
            "description_length": 4,
            "city": "Krakow",
            "district": "Centrum",
            "street": "Florianska",
            "latitude": 50.0614,
            "longitude": 19.9372,
            "area_m2": 68.0,
            "rooms": 3,
            "floor": 2,
            "total_floors": 5,
            "year_built": 2010,
            "property_type": "apartment",
            "market_type": "secondary",
            "listing_type": "agency",
            "heating_type": "municipal",
            "building_material": "brick",
            "has_lift": True,
            "has_balcony": True,
            "has_terrace": False,
            "has_floor_plan": True,
            "parking": "garage",
            "has_storage": False,
            "photo_count": 2,
            "photo_paths": ["otodom/123/photo-1.jpg"],
            "date_posted": "2026-01-15T10:30:00+00:00",
            "date_scraped": "2026-03-25T10:00:00+00:00",
            "price_pln": 850000,
            "price_per_m2": 12500,
        }
    )
    item.update(overrides)
    return item


def test_open_spider_requires_database_url():
    pipeline = DatabasePipeline()

    with pytest.raises(NotConfigured):
        pipeline.open_spider(SimpleNamespace(name="otodom"))


def test_from_crawler_disabled_by_default_flag():
    crawler = _make_crawler(use_db_slug_queue=False, database_url="postgresql://example/test")

    with pytest.raises(NotConfigured, match="USE_DB_SLUG_QUEUE=False"):
        DatabasePipeline.from_crawler(crawler)


def test_from_crawler_requires_database_url_when_enabled():
    crawler = _make_crawler(use_db_slug_queue=True, database_url=None)

    with pytest.raises(NotConfigured, match="DATABASE_URL is required"):
        DatabasePipeline.from_crawler(crawler)


def test_from_crawler_enabled_with_database_url():
    crawler = _make_crawler(use_db_slug_queue=True, database_url="postgresql://example/test")

    pipeline = DatabasePipeline.from_crawler(crawler)

    assert isinstance(pipeline, DatabasePipeline)
    assert pipeline.database_url == "postgresql://example/test"


def test_process_item_stores_raw_listing():
    connection = FakeConnection(fetchone_results=[("raw-listing-uuid",)])
    pipeline = DatabasePipeline(database_url="postgresql://example/test")
    pipeline.connection = connection

    item = _build_item()
    result = pipeline.process_item(item, spider=SimpleNamespace(name="otodom"))

    assert result is item
    assert connection.transaction_count == 1
    assert connection.transaction_exits == [None]
    assert len(connection.cursor_obj.executed) == 1

    raw_sql, raw_params = connection.cursor_obj.executed[0]
    assert raw_sql == storage.RAW_LISTING_INSERT_SQL
    assert raw_params[storage.RAW_LISTING_COLUMNS.index("source_portal")] == "otodom"
    assert raw_params[storage.RAW_LISTING_COLUMNS.index("has_parking")] is True
    assert raw_params[storage.RAW_LISTING_COLUMNS.index("parking")] == "garage"
    assert raw_params[storage.RAW_LISTING_COLUMNS.index("description_length")] == 4
    assert raw_params[storage.RAW_LISTING_COLUMNS.index("has_floor_plan")] is True
    assert raw_params[storage.RAW_LISTING_COLUMNS.index("date_posted")] == "2026-01-15T10:30:00+00:00"
    assert raw_params[storage.RAW_LISTING_COLUMNS.index("photo_paths")] == [
        "otodom/123/photo-1.jpg"
    ]
    assert raw_params[storage.RAW_LISTING_COLUMNS.index("price_pln")] == 850000
    assert raw_params[storage.RAW_LISTING_COLUMNS.index("price_per_m2")] == 12500


def test_process_item_ignores_unique_violation():
    class UniqueViolationError(Exception):
        sqlstate = "23505"

    connection = FakeConnection(fetchone_results=[])

    def raise_unique_violation(*args, **kwargs):
        raise UniqueViolationError("duplicate key")

    connection.cursor_obj.execute = raise_unique_violation

    pipeline = DatabasePipeline(database_url="postgresql://example/test")
    pipeline.connection = connection

    assert pipeline.process_item(_build_item(), spider=SimpleNamespace(name="otodom"))
    assert pipeline._raw_listing_duplicates == 1


def test_process_item_writes_rejection_file_on_db_error(tmp_path):
    connection = FakeConnection(fetchone_results=[])

    def raise_db_error(*args, **kwargs):
        raise RuntimeError("database is down")

    connection.cursor_obj.execute = raise_db_error

    pipeline = DatabasePipeline(database_url="postgresql://example/test")
    pipeline.connection = connection
    pipeline._reject_file = open(tmp_path / "rejected_otodom.jsonl", "a", encoding="utf-8")

    with pytest.raises(DropItem, match="db_error"):
        pipeline.process_item(_build_item(), spider=SimpleNamespace(name="otodom"))

    assert pipeline._raw_listing_errors == 1

    pipeline._reject_file.close()
    contents = (tmp_path / "rejected_otodom.jsonl").read_text(encoding="utf-8").strip()
    payload = json.loads(contents)
    assert payload["_drop_reason"] == "db_error"
    assert payload["_drop_error"] == "database is down"


# ── SlugCollectionItem handling ───────────────────────────────────────────


def _build_slug_item(**overrides):
    item = SlugCollectionItem()
    item.update(
        {
            "id": "aaaaaaaa-0000-0000-0000-000000000001",
            "run_id": "run-abc",
            "portal": "otodom",
            "slug": "mieszkanie-krakow-test-12345",
            "full_url": "https://www.otodom.pl/pl/oferta/mieszkanie-krakow-test-12345",
            "observed_at": "2026-03-29T10:00:00+00:00",
        }
    )
    item.update(overrides)
    return item


def test_process_slug_item_inserts_raw_slug():
    connection = FakeConnection(fetchone_results=[])
    pipeline = DatabasePipeline(database_url="postgresql://example/test")
    pipeline.connection = connection

    item = _build_slug_item()
    result = pipeline.process_item(item)

    assert result is item
    assert connection.transaction_count == 1
    assert len(connection.cursor_obj.executed) == 1

    sql, params = connection.cursor_obj.executed[0]
    assert sql == storage.RAW_SLUG_INSERT_SQL
    assert params[storage.RAW_SLUG_COLUMNS.index("slug")] == "mieszkanie-krakow-test-12345"
    assert params[storage.RAW_SLUG_COLUMNS.index("portal")] == "otodom"
    assert params[storage.RAW_SLUG_COLUMNS.index("run_id")] == "run-abc"


def test_process_slug_item_passes_through_without_connection():
    """Pipeline silently passes slug items when no DB connection is open."""
    pipeline = DatabasePipeline(database_url="postgresql://example/test")
    # connection deliberately not set (simulates no DATABASE_URL path)

    item = _build_slug_item()
    result = pipeline.process_item(item)

    assert result is item


def test_process_slug_item_logs_warning_on_error():
    """A DB error on slug insertion is logged as a warning, not re-raised."""
    connection = FakeConnection(fetchone_results=[])

    def raise_error(*args, **kwargs):
        raise RuntimeError("constraint violation")

    connection.cursor_obj.execute = raise_error

    pipeline = DatabasePipeline(database_url="postgresql://example/test")
    pipeline.connection = connection

    # Should not raise — slug errors are non-fatal
    result = pipeline.process_item(_build_slug_item())
    assert isinstance(result, SlugCollectionItem)
    assert pipeline._raw_slug_errors == 1


def test_process_item_success_increments_listing_counter():
    connection = FakeConnection(fetchone_results=[])
    pipeline = DatabasePipeline(database_url="postgresql://example/test")
    pipeline.connection = connection

    result = pipeline.process_item(_build_item(), spider=SimpleNamespace(name="otodom"))

    assert isinstance(result, RawListingItem)
    assert pipeline._raw_listing_inserted == 1


def test_process_slug_item_success_increments_slug_counter():
    connection = FakeConnection(fetchone_results=[])
    pipeline = DatabasePipeline(database_url="postgresql://example/test")
    pipeline.connection = connection

    result = pipeline.process_item(_build_slug_item())

    assert isinstance(result, SlugCollectionItem)
    assert pipeline._raw_slug_inserted == 1


def test_close_spider_logs_summary_with_bounded_counters():
    connection = FakeConnection(fetchone_results=[])
    pipeline = DatabasePipeline(database_url="postgresql://example/test")
    pipeline.connection = connection
    pipeline._logger = Mock()
    pipeline._raw_listing_inserted = 3
    pipeline._raw_listing_duplicates = 1
    pipeline._raw_listing_errors = 2
    pipeline._raw_slug_inserted = 5
    pipeline._raw_slug_errors = 1

    pipeline.close_spider(SimpleNamespace(name="otodom"))

    pipeline._logger.info.assert_called_with(
        "Database pipeline summary",
        raw_listing_inserted=3,
        raw_listing_duplicates=1,
        raw_listing_errors=2,
        raw_slug_inserted=5,
        raw_slug_errors=1,
    )


# ── storage.db helpers ────────────────────────────────────────────────────


def test_build_raw_slug_record_maps_fields():
    item = _build_slug_item()
    record = storage.build_raw_slug_record(item)

    assert record["slug"] == "mieszkanie-krakow-test-12345"
    assert record["portal"] == "otodom"
    assert record["run_id"] == "run-abc"
    assert record["full_url"] == "https://www.otodom.pl/pl/oferta/mieszkanie-krakow-test-12345"
    # observed_at should be a datetime object
    from datetime import datetime
    assert isinstance(record["observed_at"], datetime)


def test_build_slug_run_record_maps_fields():
    from property_scraper.items import SlugRunMetaItem

    item = SlugRunMetaItem()
    item.update(
        {
            "run_id": "run-xyz",
            "portal": "otodom",
            "city": "krakow",
            "started_at": "2026-03-29T09:00:00+00:00",
            "ended_at": "2026-03-29T09:05:00+00:00",
            "runtime_seconds": 300.0,
            "completion_reason": "finished",
            "parameters": {
                "city": "krakow",
                "max_pages": "5",
                "use_db_slug_queue": True,
            },
            "total_advertised": 200,
            "investments_found": 3,
            "slug_count": 195,
        }
    )
    record = storage.build_slug_run_record(item)

    assert record["run_id"] == "run-xyz"
    assert record["city"] == "krakow"
    assert record["slug_count"] == 195
    assert record["investments_found"] == 3
    assert record["parameters"] == {
        "city": "krakow",
        "max_pages": "5",
        "use_db_slug_queue": True,
    }


def test_refresh_slug_queue_executes_upsert():
    connection = FakeConnection(fetchone_results=[])
    storage.refresh_slug_queue(connection)

    assert connection.transaction_count == 1
    assert len(connection.cursor_obj.executed) == 1
    sql, params = connection.cursor_obj.executed[0]
    assert "INSERT INTO slugs" in sql
    assert "ON CONFLICT" in sql
    assert params is None  # no bind params — pure SQL