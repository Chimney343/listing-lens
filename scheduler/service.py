"""APScheduler integration for spider jobs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from scheduler.config import CronSchedule, IntervalSchedule, ScheduleSpec, SpiderJob, SpiderJobManifest


RunnerFn = Callable[..., Any]


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
