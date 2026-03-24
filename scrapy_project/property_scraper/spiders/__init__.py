"""Spiders for property portals."""

from .otodom import OtodomSlugSpider, OtodomDetailSpider
from .gratka import GratkaSpider
from .morizon import MorizonSpider

__all__ = [
    "OtodomSlugSpider",
    "OtodomDetailSpider",
    "GratkaSpider",
    "MorizonSpider",
]