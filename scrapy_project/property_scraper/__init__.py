"""Property scraper package – Scrapy spiders, items, pipelines, and configuration."""

from .area_config import SearchArea, build_otodom_url
from .items import RawListingItem, RawJsonItem, SlugCollectionItem, SlugRunMetaItem
from .pipelines import ValidationPipeline, PhotoDownloadPipeline, DatabasePipeline
from .settings import DATA_DIR

__all__ = [
    "SearchArea",
    "build_otodom_url",
    "RawListingItem",
    "RawJsonItem",
    "SlugCollectionItem",
    "SlugRunMetaItem",
    "ValidationPipeline",
    "PhotoDownloadPipeline",
    "DatabasePipeline",
    "DATA_DIR",
]