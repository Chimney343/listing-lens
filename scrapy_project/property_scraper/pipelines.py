import json
from pathlib import Path
from typing import Any, Optional, Union

import structlog

import scrapy
from scrapy import Spider
from scrapy.exceptions import DropItem, NotConfigured

from property_scraper.items import RawListingItem
from property_scraper import storage

logger = structlog.get_logger(__name__)


class ValidationPipeline:
    def open_spider(self, spider: Spider) -> None:
        # Use spider's run_dir if available, otherwise fallback to current directory
        if hasattr(spider, 'run_dir'):
            spider.run_dir.mkdir(parents=True, exist_ok=True)
            reject_path = spider.run_dir / f"rejected_{spider.name}.jsonl"
            self._reject_file = open(reject_path, "a", encoding="utf-8")
            logger.debug("ValidationPipeline writing to reject file", path=str(reject_path))
        else:
            self._reject_file = open(f"rejected_{spider.name}.jsonl", "a", encoding="utf-8")

    def close_spider(self, spider: Spider) -> None:
        self._reject_file.close()

    def process_item(
        self, item: Any, spider: Optional[Spider] = None
    ) -> Union[Any, scrapy.Item]:
        if not isinstance(item, RawListingItem):
            return item
        reason = None
        if not item.get("source_url"):
            reason = "missing_source_url"
        elif not item.get("title"):
            reason = "missing_title"
        elif not item.get("price_pln") and not item.get("area_m2"):
            reason = "no_price_or_area"

        if reason:
            self._reject_file.write(
                json.dumps({**dict(item), "_drop_reason": reason}, ensure_ascii=False) + "\n"
            )
            raise scrapy.exceptions.DropItem(reason)
        return item



class PhotoDownloadPipeline:
    """Stub — full implementation in Stage 3 (Storage / MinIO)."""

    def process_item(
        self, item: Any, spider: Optional[Spider] = None
    ) -> Union[Any, scrapy.Item]:
        if not isinstance(item, RawListingItem):
            return item
        if "photo_paths" not in item:
            item["photo_paths"] = []
        return item


class DatabasePipeline:
    """Persist validated listings and price observations in PostgreSQL."""

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url
        self.connection = None
        self._reject_file = None

    @classmethod
    def from_crawler(cls, crawler):
        return cls(database_url=crawler.settings.get("DATABASE_URL"))

    def open_spider(self, spider: Spider) -> None:
        if not self.database_url:
            raise NotConfigured("DATABASE_URL is required for DatabasePipeline")

        self.connection = storage.connect(self.database_url)

        if hasattr(spider, "run_dir"):
            spider.run_dir.mkdir(parents=True, exist_ok=True)
            reject_path = spider.run_dir / f"rejected_{spider.name}.jsonl"
            self._reject_file = open(reject_path, "a", encoding="utf-8")
            logger.debug("DatabasePipeline writing to reject file", path=str(reject_path))

    def close_spider(self, spider: Spider) -> None:
        if self._reject_file is not None:
            self._reject_file.close()
            self._reject_file = None

        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def _write_rejection(self, item: RawListingItem, error: Exception) -> None:
        if self._reject_file is None:
            return

        self._reject_file.write(
            json.dumps(
                {
                    **dict(item),
                    "_drop_reason": "db_error",
                    "_drop_error": str(error),
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        self._reject_file.flush()

    @staticmethod
    def _is_unique_violation(error: Exception) -> bool:
        return getattr(error, "sqlstate", None) == "23505"

    def process_item(
        self, item: Any, spider: Optional[Spider] = None
    ) -> Union[Any, scrapy.Item]:
        if not isinstance(item, RawListingItem):
            return item

        if self.connection is None:
            raise NotConfigured("DatabasePipeline must be opened before processing items")

        listing_record = storage.build_listing_record(item)
        price_value = item.get("price_pln")

        try:
            with self.connection.transaction():
                with self.connection.cursor() as cursor:
                    cursor.execute(
                        storage.LISTING_INSERT_SQL,
                        [listing_record[column] for column in storage.LISTING_COLUMNS],
                    )
                    listing_id = cursor.fetchone()[0]

                    if price_value is not None:
                        cursor.execute(storage.PRICE_LOOKUP_SQL, (listing_id,))
                        previous_row = cursor.fetchone()
                        previous_price = previous_row[0] if previous_row else None

                        if storage.has_price_changed(price_value, previous_price):
                            price_record = storage.build_price_record(
                                listing_id,
                                item,
                                listing_record["last_scraped_at"],
                            )
                            cursor.execute(
                                storage.PRICE_INSERT_SQL,
                                (
                                    price_record["listing_id"],
                                    price_record["price_pln"],
                                    price_record["price_per_m2"],
                                    price_record["observed_at"],
                                    price_record["source"],
                                ),
                            )
        except Exception as error:
            if self._is_unique_violation(error):
                logger.warning(
                    "Database unique violation ignored",
                    source_url=item.get("source_url"),
                    error=str(error),
                )
                return item

            logger.error(
                "Database write failed",
                source_url=item.get("source_url"),
                error=str(error),
                error_type=error.__class__.__name__,
            )
            self._write_rejection(item, error)
            raise DropItem("db_error") from error

        logger.debug(
            "DatabasePipeline stored listing",
            source_url=item.get("source_url"),
            source_portal=item.get("source_portal"),
        )
        return item
