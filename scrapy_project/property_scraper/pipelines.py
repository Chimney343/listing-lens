import hashlib
import logging

import scrapy

logger = logging.getLogger(__name__)


class ValidationPipeline:
    def process_item(self, item, spider):
        if not item.get("source_url"):
            raise scrapy.exceptions.DropItem("Missing source_url")
        if not item.get("title"):
            raise scrapy.exceptions.DropItem(f"Missing title: {item.get('source_url')}")
        if not item.get("price_pln") and not item.get("area_m2"):
            raise scrapy.exceptions.DropItem(f"No price or area: {item.get('source_url')}")
        return item


class DeduplicationPipeline:
    def process_item(self, item, spider):
        parts = "|".join([
            str(item.get("district", "none")).lower().strip(),
            f"{item.get('area_m2', 0):.1f}" if item.get("area_m2") else "none",
            str(item.get("floor", "none")),
            str(item.get("price_pln", "none")),
            str(item.get("rooms", "none")),
            str(item.get("street", "none")).lower().strip(),
        ])
        item["listing_hash"] = hashlib.sha256(parts.encode()).hexdigest()[:16]
        return item


class PhotoDownloadPipeline:
    """Stub — full implementation in Stage 3 (Storage / MinIO)."""

    def process_item(self, item, spider):
        item["photo_paths"] = []
        return item


class DatabasePipeline:
    """Stub — full implementation in Stage 3 (Storage / PostgreSQL)."""

    def process_item(self, item, spider):
        logger.debug("DatabasePipeline stub: %s", item.get("source_url"))
        return item
