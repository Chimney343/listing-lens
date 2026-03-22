import json
import logging
from pathlib import Path
from typing import Any, Optional, Union

import scrapy
from scrapy import Spider

from property_scraper.items import RawListingItem

logger = logging.getLogger(__name__)


class ValidationPipeline:
    def open_spider(self, spider: Spider) -> None:
        # Use spider's run_dir if available, otherwise fallback to current directory
        if hasattr(spider, 'run_dir'):
            spider.run_dir.mkdir(parents=True, exist_ok=True)
            reject_path = spider.run_dir / f"rejected_{spider.name}.jsonl"
            self._reject_file = open(reject_path, "a", encoding="utf-8")
            spider.logger.debug("ValidationPipeline writing to %s", reject_path)
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
        item["photo_paths"] = []
        return item


class DatabasePipeline:
    """Stub — full implementation in Stage 3 (Storage / PostgreSQL)."""

    def process_item(
        self, item: Any, spider: Optional[Spider] = None
    ) -> Union[Any, scrapy.Item]:
        if not isinstance(item, RawListingItem):
            return item
        logger.debug("DatabasePipeline stub: %s", item.get("source_url"))
        return item
