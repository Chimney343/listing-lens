import json
import logging

import scrapy

logger = logging.getLogger(__name__)


class ValidationPipeline:
    def open_spider(self, spider):
        self._reject_file = open(f"rejected_{spider.name}.jsonl", "a", encoding="utf-8")

    def close_spider(self, spider):
        self._reject_file.close()

    def process_item(self, item, spider=None):
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

    def process_item(self, item, spider=None):
        item["photo_paths"] = []
        return item


class DatabasePipeline:
    """Stub — full implementation in Stage 3 (Storage / PostgreSQL)."""

    def process_item(self, item, spider=None):
        logger.debug("DatabasePipeline stub: %s", item.get("source_url"))
        return item
