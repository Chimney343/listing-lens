"""Tests for scheduler command generation."""

from __future__ import annotations

import pytest

from scheduler.config import SpiderJobManifest
from scheduler.jobs import build_spider_command


def _manifest_dict() -> dict:
    return {
        "search_profiles": {
            "krakow_core": {
                "city": "krakow",
                "voivodeship": "malopolskie",
                "powiat": "krakowski",
                "gmina": "gmina-miejska--krakow",
                "property_type": "mieszkanie",
                "districts": ["podgorze", "debniki"],
                "price_min": 450000,
                "price_max": 1500000,
                "area_min": 25,
                "area_max": 50,
                "terrain_area_min": 50,
                "terrain_area_max": 100,
                "price_per_meter_min": 5000,
                "price_per_meter_max": 10000,
                "build_year_min": 1950,
                "build_year_max": 2025,
                "rooms_number": ["ONE", "TWO", "THREE", "FIVE", "FOUR"],
                "building_material": ["BRICK"],
                "extras": ["IS_BUNGALOV", "HAS_PHOTOS"],
                "max_pages": 20,
            }
        },
        "jobs": [
            {
                "job_id": "otodom-krakow-slugs",
                "enabled": True,
                "portal": "otodom",
                "spider_kind": "slugs",
                "search_profile": "krakow_core",
                "schedule": {"type": "cron", "expression": "0 6 * * *"},
            },
            {
                "job_id": "otodom-krakow-detail",
                "enabled": True,
                "portal": "otodom",
                "spider_kind": "detail",
                "search_profile": "krakow_core",
                "use_db_slug_queue": True,
                "schedule": {"type": "interval", "hours": 8},
            },
        ],
    }


def test_build_spider_command_for_slugs_job():
    manifest = SpiderJobManifest.model_validate(_manifest_dict())
    job = manifest.jobs[0]

    command = build_spider_command(job=job, manifest=manifest, correlation_id="run-123")

    assert command[:5] == ["poetry", "run", "scrapy", "crawl", "otodom_slugs"]
    assert "city=krakow" in command
    assert "districts=podgorze,debniki" in command
    assert "price_min=450000" in command
    assert "area_min=25" in command
    assert "area_max=50" in command
    assert "terrain_area_min=50" in command
    assert "terrain_area_max=100" in command
    assert "price_per_meter_min=5000" in command
    assert "price_per_meter_max=10000" in command
    assert "build_year_min=1950" in command
    assert "build_year_max=2025" in command
    assert "rooms_number=ONE,TWO,THREE,FIVE,FOUR" in command
    assert "building_material=BRICK" in command
    assert "extras=IS_BUNGALOV,HAS_PHOTOS" in command
    assert "max_pages=20" in command
    assert "correlation_id=run-123" in command


def test_build_spider_command_for_detail_job_in_db_mode():
    manifest = SpiderJobManifest.model_validate(_manifest_dict())
    job = manifest.jobs[1]

    command = build_spider_command(job=job, manifest=manifest, correlation_id="run-xyz")

    assert command[:5] == ["poetry", "run", "scrapy", "crawl", "otodom_detail"]
    assert "use_db_slug_queue=1" in command
    assert "USE_DB_SLUG_QUEUE=1" in command
    assert "city=krakow" in command
    assert "correlation_id=run-xyz" in command


def test_build_spider_command_rejects_unsupported_portal():
    payload = _manifest_dict()
    payload["jobs"][0]["portal"] = "gratka"
    manifest = SpiderJobManifest.model_validate(payload)

    with pytest.raises(NotImplementedError, match="gratka"):
        build_spider_command(job=manifest.jobs[0], manifest=manifest)
