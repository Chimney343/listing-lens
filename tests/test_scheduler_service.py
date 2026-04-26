"""Tests for APScheduler trigger conversion and registration."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from scheduler.config import SpiderJobManifest
from scheduler.service import build_trigger, register_jobs


class FakeScheduler:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def add_job(self, func, trigger, id, kwargs, replace_existing, max_instances, coalesce):
        self.calls.append(
            {
                "func": func,
                "trigger": trigger,
                "id": id,
                "kwargs": kwargs,
                "replace_existing": replace_existing,
                "max_instances": max_instances,
                "coalesce": coalesce,
            }
        )


def _manifest_dict() -> dict:
    return {
        "search_profiles": {
            "krakow_core": {
                "city": "krakow",
            }
        },
        "jobs": [
            {
                "job_id": "enabled-cron",
                "enabled": True,
                "portal": "otodom",
                "spider_kind": "slugs",
                "search_profile": "krakow_core",
                "schedule": {"type": "cron", "expression": "0 6 * * *"},
            },
            {
                "job_id": "disabled-interval",
                "enabled": False,
                "portal": "otodom",
                "spider_kind": "detail",
                "search_profile": "krakow_core",
                "schedule": {"type": "interval", "hours": 12},
            },
        ],
    }


def test_build_trigger_for_cron_schedule():
    manifest = SpiderJobManifest.model_validate(_manifest_dict())
    trigger = build_trigger(manifest.jobs[0].schedule)

    assert trigger.__class__.__name__ == "CronTrigger"


def test_build_trigger_for_interval_schedule():
    manifest = SpiderJobManifest.model_validate(
        {
            "search_profiles": {"krakow_core": {"city": "krakow"}},
            "jobs": [
                {
                    "job_id": "interval-job",
                    "enabled": True,
                    "portal": "otodom",
                    "spider_kind": "detail",
                    "search_profile": "krakow_core",
                    "schedule": {
                        "type": "interval",
                        "hours": 6,
                        "jitter_seconds": 900,
                    },
                }
            ],
        }
    )

    trigger = build_trigger(manifest.jobs[0].schedule)

    assert trigger.__class__.__name__ == "IntervalTrigger"
    assert trigger.jitter == 900


def test_build_trigger_for_random_daily_schedule(monkeypatch):
    manifest = SpiderJobManifest.model_validate(
        {
            "search_profiles": {"krakow_core": {"city": "krakow"}},
            "jobs": [
                {
                    "job_id": "random-daily-job",
                    "enabled": True,
                    "portal": "otodom",
                    "spider_kind": "slugs",
                    "search_profile": "krakow_core",
                    "schedule": {
                        "type": "random_daily",
                        "start_time": "06:00",
                        "end_time": "08:00",
                    },
                }
            ],
        }
    )
    monkeypatch.setattr("scheduler.service.random.randint", lambda start, end: 1800)

    trigger = build_trigger(manifest.jobs[0].schedule)
    now = datetime(2026, 4, 26, 5, 0, tzinfo=ZoneInfo("Europe/Warsaw"))
    next_fire_time = trigger.get_next_fire_time(previous_fire_time=None, now=now)

    assert trigger.__class__.__name__ == "RandomDailyTrigger"
    assert next_fire_time == datetime(2026, 4, 26, 6, 30, tzinfo=ZoneInfo("Europe/Warsaw"))


def test_register_jobs_adds_enabled_jobs_only():
    manifest = SpiderJobManifest.model_validate(_manifest_dict())
    scheduler = FakeScheduler()

    def fake_runner(*, job, manifest):
        return None

    register_jobs(scheduler=scheduler, manifest=manifest, runner=fake_runner)

    assert len(scheduler.calls) == 1
    assert scheduler.calls[0]["id"] == "enabled-cron"
    assert scheduler.calls[0]["kwargs"]["job"].job_id == "enabled-cron"
