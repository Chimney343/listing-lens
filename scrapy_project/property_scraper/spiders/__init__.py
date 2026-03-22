"""Spiders for property portals."""

from .otodom import OtodomSpider
from .gratka import GratkaSpider
from .morizon import MorizonSpider

__all__ = [
    "OtodomSpider",
    "GratkaSpider",
    "MorizonSpider",
]