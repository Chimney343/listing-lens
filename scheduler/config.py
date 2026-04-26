"""Typed manifest models for spider scheduling."""

from __future__ import annotations

import json
from datetime import time
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class SearchProfile(BaseModel):
    """Search filters shared by one or more spider jobs."""

    city: str = "mielec"
    voivodeship: str | None = None
    powiat: str | None = None
    gmina: str | None = None
    property_type: str | None = None
    districts: list[str] = Field(default_factory=list)
    price_min: int | None = None
    price_max: int | None = None
    area_min: float | None = None
    area_max: float | None = None
    terrain_area_min: float | None = None
    terrain_area_max: float | None = None
    price_per_meter_min: int | None = None
    price_per_meter_max: int | None = None
    build_year_min: int | None = None
    build_year_max: int | None = None
    rooms_number: list[str] = Field(default_factory=list)
    building_material: list[str] = Field(default_factory=list)
    extras: list[str] = Field(default_factory=list)
    max_pages: int | None = None


class CronSchedule(BaseModel):
    """Cron-based schedule using standard crontab format."""

    type: Literal["cron"]
    expression: str


class IntervalSchedule(BaseModel):
    """Interval-based schedule with optional jitter."""

    type: Literal["interval"]
    seconds: int | None = None
    minutes: int | None = None
    hours: int | None = None
    days: int | None = None
    jitter_seconds: int | None = None

    @model_validator(mode="after")
    def validate_interval(self) -> "IntervalSchedule":
        values = {
            "seconds": self.seconds,
            "minutes": self.minutes,
            "hours": self.hours,
            "days": self.days,
        }
        if not any(value is not None for value in values.values()):
            raise ValueError("Interval schedule requires at least one time unit")

        for name, value in values.items():
            if value is not None and value <= 0:
                raise ValueError(f"Interval schedule field '{name}' must be > 0")

        if self.jitter_seconds is not None and self.jitter_seconds < 0:
            raise ValueError("Interval schedule field 'jitter_seconds' must be >= 0")

        return self


def _parse_clock_time(value: str, *, field_name: str) -> time:
    try:
        parsed = time.fromisoformat(value)
    except ValueError as error:
        raise ValueError(
            f"Random daily schedule field '{field_name}' must be a valid HH:MM or HH:MM:SS time"
        ) from error

    if parsed.tzinfo is not None:
        raise ValueError(f"Random daily schedule field '{field_name}' must not include timezone info")

    return parsed


class RandomDailySchedule(BaseModel):
    """Run once per day at a random time within a bounded local-time window."""

    type: Literal["random_daily"]
    start_time: str
    end_time: str

    @model_validator(mode="after")
    def validate_window(self) -> "RandomDailySchedule":
        start_clock = _parse_clock_time(self.start_time, field_name="start_time")
        end_clock = _parse_clock_time(self.end_time, field_name="end_time")

        if start_clock >= end_clock:
            raise ValueError("Random daily schedule field 'start_time' must be earlier than 'end_time'")

        return self


ScheduleSpec = Annotated[CronSchedule | IntervalSchedule | RandomDailySchedule, Field(discriminator="type")]


class SpiderJob(BaseModel):
    """Single scheduled spider run definition."""

    job_id: str
    enabled: bool = True
    portal: Literal["otodom", "gratka", "morizon"]
    spider_kind: Literal["slugs", "detail"]
    search_profile: str | None = None
    use_db_slug_queue: bool = False
    extra_args: dict[str, str] = Field(default_factory=dict)
    schedule: ScheduleSpec


class SpiderJobManifest(BaseModel):
    """Top-level manifest containing profiles and jobs."""

    search_profiles: dict[str, SearchProfile] = Field(default_factory=dict)
    jobs: list[SpiderJob]

    @model_validator(mode="after")
    def validate_references(self) -> "SpiderJobManifest":
        for job in self.jobs:
            if job.search_profile and job.search_profile not in self.search_profiles:
                raise ValueError(
                    f"Job '{job.job_id}' references unknown search_profile '{job.search_profile}'"
                )
        return self


def load_manifest_from_file(path: str | Path) -> SpiderJobManifest:
    """Load a scheduler manifest from YAML or JSON."""

    manifest_path = Path(path)
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest file not found: {manifest_path}")

    suffix = manifest_path.suffix.lower()
    if suffix == ".json":
        raw_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    elif suffix in {".yaml", ".yml"}:
        raw_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    else:
        raise ValueError(
            f"Unsupported manifest format '{suffix}'. Use .json, .yaml, or .yml"
        )

    if raw_data is None:
        raw_data = {}

    return SpiderJobManifest.model_validate(raw_data)
