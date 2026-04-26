"""Tests for multi-job scheduler manifest parsing."""

from __future__ import annotations

import pytest

from scheduler.config import CronSchedule, IntervalSchedule, RandomDailySchedule, load_manifest_from_file


def test_load_manifest_from_yaml(tmp_path):
    manifest_path = tmp_path / "spider_jobs.yaml"
    manifest_path.write_text(
        """
search_profiles:
  krakow_core:
    city: krakow
    voivodeship: malopolskie
    powiat: krakowski
    gmina: gmina-miejska--krakow
    property_type: mieszkanie
    districts:
      - podgorze
      - debniki
    price_min: 400000
    price_max: 1200000
    area_min: 25
    area_max: 50
    terrain_area_min: 50
    terrain_area_max: 100
    price_per_meter_min: 5000
    price_per_meter_max: 10000
    build_year_min: 1950
    build_year_max: 2025
    rooms_number:
      - ONE
      - TWO
      - THREE
      - FIVE
      - FOUR
    building_material:
      - BRICK
    extras:
      - IS_BUNGALOV
      - HAS_PHOTOS
jobs:
  - job_id: otodom-krakow-slugs
    enabled: true
    portal: otodom
    spider_kind: slugs
    search_profile: krakow_core
    schedule:
      type: cron
      expression: "0 6 * * *"

  - job_id: otodom-krakow-detail
    enabled: true
    portal: otodom
    spider_kind: detail
    search_profile: krakow_core
    use_db_slug_queue: true
    schedule:
      type: interval
      hours: 12
      jitter_seconds: 1800
""".lstrip(),
        encoding="utf-8",
    )

    manifest = load_manifest_from_file(manifest_path)

    assert len(manifest.jobs) == 2
    assert "krakow_core" in manifest.search_profiles
    assert isinstance(manifest.jobs[0].schedule, CronSchedule)
    assert isinstance(manifest.jobs[1].schedule, IntervalSchedule)
    assert manifest.jobs[1].use_db_slug_queue is True
    profile = manifest.search_profiles["krakow_core"]
    assert profile.area_min == 25
    assert profile.area_max == 50
    assert profile.terrain_area_min == 50
    assert profile.terrain_area_max == 100
    assert profile.price_per_meter_min == 5000
    assert profile.price_per_meter_max == 10000
    assert profile.build_year_min == 1950
    assert profile.build_year_max == 2025
    assert profile.rooms_number == ["ONE", "TWO", "THREE", "FIVE", "FOUR"]
    assert profile.building_material == ["BRICK"]
    assert profile.extras == ["IS_BUNGALOV", "HAS_PHOTOS"]


def test_manifest_rejects_unknown_search_profile(tmp_path):
    manifest_path = tmp_path / "spider_jobs.yaml"
    manifest_path.write_text(
        """
search_profiles: {}
jobs:
  - job_id: bad-job
    enabled: true
    portal: otodom
    spider_kind: slugs
    search_profile: missing-profile
    schedule:
      type: cron
      expression: "0 6 * * *"
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing-profile"):
        load_manifest_from_file(manifest_path)


def test_interval_schedule_requires_one_time_unit(tmp_path):
    manifest_path = tmp_path / "spider_jobs.yaml"
    manifest_path.write_text(
        """
search_profiles:
  krakow_core:
    city: krakow
jobs:
  - job_id: bad-interval
    enabled: true
    portal: otodom
    spider_kind: detail
    search_profile: krakow_core
    schedule:
      type: interval
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="at least one"):
        load_manifest_from_file(manifest_path)


def test_load_manifest_with_random_daily_schedule(tmp_path):
    manifest_path = tmp_path / "spider_jobs.yaml"
    manifest_path.write_text(
        """
search_profiles:
  krakow_core:
    city: krakow
jobs:
  - job_id: otodom-krakow-slugs-random
    enabled: true
    portal: otodom
    spider_kind: slugs
    search_profile: krakow_core
    use_db_slug_queue: true
    schedule:
      type: random_daily
      start_time: "06:00"
      end_time: "08:30"
""".lstrip(),
        encoding="utf-8",
    )

    manifest = load_manifest_from_file(manifest_path)

    assert len(manifest.jobs) == 1
    assert isinstance(manifest.jobs[0].schedule, RandomDailySchedule)
    assert manifest.jobs[0].schedule.start_time == "06:00"
    assert manifest.jobs[0].schedule.end_time == "08:30"


def test_random_daily_schedule_rejects_inverted_window(tmp_path):
    manifest_path = tmp_path / "spider_jobs.yaml"
    manifest_path.write_text(
        """
search_profiles:
  krakow_core:
    city: krakow
jobs:
  - job_id: otodom-krakow-slugs-random
    enabled: true
    portal: otodom
    spider_kind: slugs
    search_profile: krakow_core
    schedule:
      type: random_daily
      start_time: "08:30"
      end_time: "06:00"
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="start_time"):
        load_manifest_from_file(manifest_path)
