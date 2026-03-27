import json
from pathlib import Path
from typing import Any, Optional, Union

import structlog

import scrapy
from scrapy import Spider
from scrapy.exceptions import DropItem, NotConfigured

from property_scraper.items import RawListingItem
from storage import db as storage

logger = structlog.get_logger(__name__)


class ValidationPipeline:
    """Validates items and writes rejections to a file.
    
    Note: File is kept open during spider execution for performance.
    Resources are guaranteed to be cleaned up via close_spider() and __del__().
    """
    
    def __init__(self) -> None:
        self._reject_file = None
    
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
        """Close reject file safely."""
        if self._reject_file is not None:
            try:
                self._reject_file.close()
            except Exception as e:
                logger.warning("Error closing reject file", error=str(e))
            finally:
                self._reject_file = None
    
    def __del__(self) -> None:
        """Safety net: ensure file is closed even if close_spider() is not called."""
        if self._reject_file is not None:
            try:
                self._reject_file.close()
            except Exception:
                pass  # Don't raise in __del__

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
            if self._reject_file is not None:
                try:
                    self._reject_file.write(
                        json.dumps({**dict(item), "_drop_reason": reason}, ensure_ascii=False) + "\n"
                    )
                    self._reject_file.flush()  # Ensure data is written
                except Exception as e:
                    logger.error("Failed to write rejection record", error=str(e))
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
    """Persist validated listings and price observations in PostgreSQL.
    
    Note: Database connection and reject file are kept open during spider
    execution for performance. Resources are guaranteed to be cleaned up
    via close_spider() and __del__().
    """

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
        """Close database connection and reject file safely."""
        if self._reject_file is not None:
            try:
                self._reject_file.close()
            except Exception as e:
                logger.warning("Error closing reject file", error=str(e))
            finally:
                self._reject_file = None

        if self.connection is not None:
            try:
                self.connection.close()
            except Exception as e:
                logger.warning("Error closing database connection", error=str(e))
            finally:
                self.connection = None
    
    def __del__(self) -> None:
        """Safety net: ensure resources are closed even if close_spider() is not called."""
        if self._reject_file is not None:
            try:
                self._reject_file.close()
            except Exception:
                pass  # Don't raise in __del__
        
        if self.connection is not None:
            try:
                self.connection.close()
            except Exception:
                pass  # Don't raise in __del__

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
