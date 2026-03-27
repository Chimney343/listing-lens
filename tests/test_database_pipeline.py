"""Tests for the PostgreSQL-backed Scrapy pipeline."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from scrapy.exceptions import DropItem, NotConfigured

from storage import db as storage
from property_scraper.items import RawListingItem
from property_scraper.pipelines import DatabasePipeline


class FakeCursor:
    def __init__(self, fetchone_results):
        self.fetchone_results = list(fetchone_results)
        self.executed = []

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


def _build_item(**overrides):
    item = RawListingItem()
    item.update(
        {
            "source_portal": "otodom",
            "source_url": "https://www.otodom.pl/pl/oferta/test-123",
            "external_id": "123",
            "title": "Przykładowe mieszkanie",
            "description": "Opis",
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
            "parking": "garage",
            "has_storage": False,
            "photo_count": 2,
            "photo_paths": ["otodom/123/photo-1.jpg"],
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


def test_process_item_stores_listing_and_price_history():
    connection = FakeConnection(fetchone_results=[("listing-uuid",), None])
    pipeline = DatabasePipeline(database_url="postgresql://example/test")
    pipeline.connection = connection

    item = _build_item()
    result = pipeline.process_item(item, spider=SimpleNamespace(name="otodom"))

    assert result is item
    assert connection.transaction_count == 1
    assert connection.transaction_exits == [None]

    listing_sql, listing_params = connection.cursor_obj.executed[0]
    assert listing_sql == storage.LISTING_INSERT_SQL
    assert listing_params[storage.LISTING_COLUMNS.index("source_portal")] == "otodom"
    assert listing_params[storage.LISTING_COLUMNS.index("has_parking")] is True
    assert listing_params[storage.LISTING_COLUMNS.index("photo_paths")] == [
        "otodom/123/photo-1.jpg"
    ]

    price_sql, price_params = connection.cursor_obj.executed[1]
    assert price_sql == storage.PRICE_LOOKUP_SQL
    insert_sql, insert_params = connection.cursor_obj.executed[2]
    assert insert_sql == storage.PRICE_INSERT_SQL
    assert insert_params[1] == 850000
    assert insert_params[2] == 12500


def test_process_item_skips_price_history_when_price_is_unchanged():
    connection = FakeConnection(fetchone_results=[("listing-uuid",), (850000,)])
    pipeline = DatabasePipeline(database_url="postgresql://example/test")
    pipeline.connection = connection

    pipeline.process_item(_build_item(), spider=SimpleNamespace(name="otodom"))

    executed_sql = [sql for sql, _ in connection.cursor_obj.executed]
    assert executed_sql == [storage.LISTING_INSERT_SQL, storage.PRICE_LOOKUP_SQL]


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

    pipeline._reject_file.close()
    contents = (tmp_path / "rejected_otodom.jsonl").read_text(encoding="utf-8").strip()
    payload = json.loads(contents)
    assert payload["_drop_reason"] == "db_error"
    assert payload["_drop_error"] == "database is down"