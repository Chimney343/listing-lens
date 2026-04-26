"""APScheduler integration for spider jobs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, time, timedelta, tzinfo
import random
from typing import Any

from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from scheduler.config import (
    CronSchedule,
    IntervalSchedule,
    RandomDailySchedule,
    ScheduleSpec,
    SpiderJob,
    SpiderJobManifest,
)


RunnerFn = Callable[..., Any]


def _parse_clock_time(value: str) -> time:
    return time.fromisoformat(value)


class RandomDailyTrigger(BaseTrigger):
    """Fire once per day at a random time inside a configured local-time window."""

    def __init__(self, *, start_time: time, end_time: time) -> None:
        self.start_time = start_time
        self.end_time = end_time
        self._cached_date: date | None = None
        self._cached_fire_time: datetime | None = None

    def get_next_fire_time(
        self,
        previous_fire_time: datetime | None,
        now: datetime,
    ) -> datetime | None:
        if now.tzinfo is None:
            raise ValueError("RandomDailyTrigger requires timezone-aware datetimes")

        if previous_fire_time is not None:
            target_date = previous_fire_time.astimezone(now.tzinfo).date() + timedelta(days=1)
            return self._pick_fire_time(target_date=target_date, timezone=now.tzinfo)

        if self._cached_fire_time is not None and self._cached_fire_time >= now:
            return self._cached_fire_time

        candidate = self._pick_fire_time(target_date=now.date(), timezone=now.tzinfo)
        if candidate <= now:
            candidate = self._pick_fire_time(
                target_date=now.date() + timedelta(days=1),
                timezone=now.tzinfo,
            )
        return candidate

    def _pick_fire_time(self, *, target_date: date, timezone: tzinfo) -> datetime:
        if self._cached_date == target_date and self._cached_fire_time is not None:
            return self._cached_fire_time

        start_at = datetime.combine(target_date, self.start_time, tzinfo=timezone)
        end_at = datetime.combine(target_date, self.end_time, tzinfo=timezone)
        window_seconds = int((end_at - start_at).total_seconds())
        offset_seconds = random.randint(0, window_seconds)
        fire_time = start_at + timedelta(seconds=offset_seconds)

        self._cached_date = target_date
        self._cached_fire_time = fire_time
        return fire_time

    def __getstate__(self) -> dict[str, str]:
        return {
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
        }

    def __setstate__(self, state: dict[str, str]) -> None:
        self.start_time = _parse_clock_time(state["start_time"])
        self.end_time = _parse_clock_time(state["end_time"])
        self._cached_date = None
        self._cached_fire_time = None


def build_trigger(schedule: ScheduleSpec) -> BaseTrigger:
    """Convert schedule config into an APScheduler trigger."""

    if isinstance(schedule, CronSchedule):
        return CronTrigger.from_crontab(schedule.expression)

    if isinstance(schedule, IntervalSchedule):
        kwargs: dict[str, int] = {}
        if schedule.seconds is not None:
            kwargs["seconds"] = schedule.seconds
        if schedule.minutes is not None:
            kwargs["minutes"] = schedule.minutes
        if schedule.hours is not None:
            kwargs["hours"] = schedule.hours
        if schedule.days is not None:
            kwargs["days"] = schedule.days
        if schedule.jitter_seconds is not None:
            kwargs["jitter"] = schedule.jitter_seconds
        return IntervalTrigger(**kwargs)

    if isinstance(schedule, RandomDailySchedule):
        return RandomDailyTrigger(
            start_time=_parse_clock_time(schedule.start_time),
            end_time=_parse_clock_time(schedule.end_time),
        )

    raise TypeError(f"Unsupported schedule type: {type(schedule)!r}")


def register_jobs(
    *,
    scheduler: Any,
    manifest: SpiderJobManifest,
    runner: RunnerFn,
) -> list[str]:
    """Register enabled jobs on a scheduler instance."""

    registered_ids: list[str] = []
    for job in manifest.jobs:
        if not job.enabled:
            continue

        scheduler.add_job(
            func=runner,
            trigger=build_trigger(job.schedule),
            id=job.job_id,
            kwargs={"job": job, "manifest": manifest},
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        registered_ids.append(job.job_id)

    return registered_ids
