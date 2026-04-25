import json
from pathlib import Path
from typing import Any, Optional, Union

import structlog

import scrapy
from scrapy import Spider
from scrapy.exceptions import DropItem, NotConfigured

from property_scraper.items import RawListingItem, SlugCollectionItem
from storage import db as storage

logger = structlog.get_logger(__name__)


class ValidationPipeline:
    """Validates items and writes rejections to a file.
    
    Note: File is kept open during spider execution for performance.
    Resources are guaranteed to be cleaned up via close_spider() and __del__().
    """
    
    def __init__(self) -> None:
        self._reject_file = None
    
    def open_spider(self, spider: Optional[Spider] = None) -> None:
        # Use spider's run_dir if available, otherwise fallback to current directory
        if spider is not None and hasattr(spider, 'run_dir'):
            spider.run_dir.mkdir(parents=True, exist_ok=True)
            reject_path = spider.run_dir / f"rejected_{spider.name}.jsonl"
            self._reject_file = open(reject_path, "a", encoding="utf-8")
            logger.debug("Writing invalid items to reject file", path=str(reject_path))
        else:
            spider_name = getattr(spider, "name", "unknown") if spider is not None else "unknown"
            self._reject_file = open(f"rejected_{spider_name}.jsonl", "a", encoding="utf-8")

    def close_spider(self, spider: Optional[Spider] = None) -> None:
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
                    logger.error("Failed to write invalid item to reject file", error=str(e))
            raise scrapy.exceptions.DropItem(reason)
        return item



class PiiFilterPipeline:
    """Redacts PII from free-text fields before storage.

    Targets: title, description only.
    Structured address fields (street, city, district) are intentionally
    preserved — they are part of the dedup hash and property identity.
    """

    _TEXT_FIELDS = ("title", "description")

    def __init__(
        self,
        *,
        entities: list[str],
        language: str,
        nlp_model: str,
        score_threshold: float,
        operators: dict,
    ) -> None:
        self._entities = entities
        self._language = language
        self._nlp_model = nlp_model
        self._score_threshold = score_threshold
        self._operators = operators

    @classmethod
    def from_crawler(cls, crawler: Any) -> "PiiFilterPipeline":
        from property_scraper.pii_filter import DEFAULT_ENTITIES  # deferred: heavy import

        if not crawler.settings.getbool("PII_ENABLED", True):
            raise NotConfigured("PII filtering disabled via PII_ENABLED=False")

        return cls(
            entities=crawler.settings.getlist("PII_ENTITIES", list(DEFAULT_ENTITIES)),
            language=crawler.settings.get("PII_LANGUAGE", "en"),
            nlp_model=crawler.settings.get("PII_NLP_MODEL", "en_core_web_sm"),
            score_threshold=crawler.settings.getfloat("PII_SCORE_THRESHOLD", 0.0),
            operators=crawler.settings.getdict("PII_OPERATORS", {}),
        )

    def open_spider(self, spider: Optional[Spider] = None) -> None:
        from property_scraper.pii_filter import PiiFilter  # deferred: heavy import
        self._filter = PiiFilter(
            entities=self._entities,
            language=self._language,
            nlp_model=self._nlp_model,
            score_threshold=self._score_threshold,
            operators=self._operators,
        )
        logger.debug("PII filter pipeline initialized", spider=getattr(spider, "name", "unknown"))

    def process_item(
        self, item: Any, spider: Optional[Spider] = None
    ) -> Union[Any, scrapy.Item]:
        if not isinstance(item, RawListingItem):
            return item
        for field in self._TEXT_FIELDS:
            original = item.get(field)
            if original:
                cleaned = self._filter.clean(original)
                if cleaned != original:
                    logger.info("PII redacted from field", field=field, spider=getattr(spider, "name", None))
                    item[field] = cleaned
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
        self._logger = logger
        self._raw_listing_inserted = 0
        self._raw_listing_duplicates = 0
        self._raw_listing_errors = 0
        self._raw_slug_inserted = 0
        self._raw_slug_errors = 0

    @classmethod
    def from_crawler(cls, crawler):
        if not crawler.settings.getbool("USE_DB_SLUG_QUEUE", False):
            raise NotConfigured("DatabasePipeline disabled via USE_DB_SLUG_QUEUE=False")

        database_url = crawler.settings.get("DATABASE_URL")
        if not database_url:
            raise NotConfigured("DATABASE_URL is required when USE_DB_SLUG_QUEUE=True")

        return cls(database_url=database_url)

    def open_spider(self, spider: Optional[Spider] = None) -> None:
        self._logger = logger.bind(spider=getattr(spider, "name", "unknown"), pipeline="database")

        if not self.database_url:
            raise NotConfigured("DATABASE_URL is required for DatabasePipeline")

        self.connection = storage.connect(self.database_url)

        if spider is not None and hasattr(spider, "run_dir"):
            spider.run_dir.mkdir(parents=True, exist_ok=True)
            reject_path = spider.run_dir / f"rejected_{spider.name}.jsonl"
            self._reject_file = open(reject_path, "a", encoding="utf-8")
            self._logger.debug("Writing invalid items to reject file", path=str(reject_path))

    def close_spider(self, spider: Optional[Spider] = None) -> None:
        """Close database connection and reject file safely."""
        self._logger.info(
            "Database pipeline summary",
            raw_listing_inserted=self._raw_listing_inserted,
            raw_listing_duplicates=self._raw_listing_duplicates,
            raw_listing_errors=self._raw_listing_errors,
            raw_slug_inserted=self._raw_slug_inserted,
            raw_slug_errors=self._raw_slug_errors,
        )

        if self._reject_file is not None:
            try:
                self._reject_file.close()
            except Exception as e:
                self._logger.warning("Error closing reject file", error=str(e))
            finally:
                self._reject_file = None

        if self.connection is not None:
            try:
                self.connection.close()
            except Exception as e:
                self._logger.warning("Error closing database connection", error=str(e))
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
        if isinstance(item, SlugCollectionItem):
            return self._process_slug_item(item)

        if not isinstance(item, RawListingItem):
            return item

        if self.connection is None:
            raise NotConfigured("DatabasePipeline must be opened before processing items")

        record = storage.build_raw_listing_record(item)

        try:
            with self.connection.transaction():
                with self.connection.cursor() as cursor:
                    cursor.execute(
                        storage.RAW_LISTING_INSERT_SQL,
                        [record[column] for column in storage.RAW_LISTING_COLUMNS],
                    )
        except Exception as error:
            if self._is_unique_violation(error):
                self._raw_listing_duplicates += 1
                self._logger.warning(
                    "Duplicate listing ignored (already in database)",
                    source_url=item.get("source_url"),
                    error=str(error),
                )
                return item

            self._raw_listing_errors += 1
            self._logger.error(
                "Failed to insert listing",
                source_url=item.get("source_url"),
                error=str(error),
                error_type=error.__class__.__name__,
            )
            self._write_rejection(item, error)
            raise DropItem("db_error") from error

        self._raw_listing_inserted += 1
        self._logger.debug(
            "Listing inserted",
            source_url=item.get("source_url"),
            source_portal=item.get("source_portal"),
        )
        return item

    def _process_slug_item(self, item: SlugCollectionItem) -> SlugCollectionItem:
        """Insert a single raw_slug observation row."""
        if self.connection is None:
            return item

        record = storage.build_raw_slug_record(item)
        try:
            with self.connection.transaction():
                with self.connection.cursor() as cursor:
                    cursor.execute(
                        storage.RAW_SLUG_INSERT_SQL,
                        [record[col] for col in storage.RAW_SLUG_COLUMNS],
                    )
            self._raw_slug_inserted += 1
        except Exception as error:
            self._raw_slug_errors += 1
            self._logger.warning(
                "Failed to insert slug",
                slug=item.get("slug"),
                error=str(error),
            )
        return item
