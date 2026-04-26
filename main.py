"""APScheduler entrypoint for scheduled spider jobs."""

from __future__ import annotations

import argparse
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler

from config.settings import settings
from logging_config import configure_logging, get_logger
from scheduler.config import load_manifest_from_file
from scheduler.runner import run_job
from scheduler.service import register_jobs


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the spider scheduler")
    parser.add_argument(
        "--jobs-file",
        default="config/spider_jobs.yaml",
        help="Path to scheduler manifest (yaml/json)",
    )
    parser.add_argument(
        "--timezone",
        default="Europe/Warsaw",
        help="Timezone used by APScheduler",
    )
    parser.add_argument(
        "--log-level",
        default=settings.log_level,
        help="Application log level",
    )
    parser.add_argument(
        "--json-logs",
        action="store_true",
        default=settings.json_logs,
        help="Emit logs as JSON",
    )
    parser.add_argument(
        "--no-json-logs",
        action="store_false",
        dest="json_logs",
        help="Emit logs as plain text",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and register jobs, then exit",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    configure_logging(
        log_level=args.log_level,
        log_dir=Path("logs"),
        json_format=args.json_logs,
        enable_file_logging=True,
        enable_console_logging=True,
    )
    log = get_logger(__name__)

    log.info(
        "scheduler_boot",
        env=settings.env,
        database_host=settings.database_host,
        log_level=args.log_level,
        json_logs=args.json_logs,
    )

    manifest = load_manifest_from_file(args.jobs_file)
    scheduler = BlockingScheduler(timezone=args.timezone)

    registered_ids = register_jobs(
        scheduler=scheduler,
        manifest=manifest,
        runner=run_job,
    )

    if not registered_ids:
        raise RuntimeError("No enabled scheduler jobs found in manifest")

    log.info(
        "Scheduler jobs registered",
        jobs_file=str(args.jobs_file),
        timezone=args.timezone,
        job_ids=registered_ids,
    )

    if args.dry_run:
        log.info("Scheduler dry-run completed", registered_job_count=len(registered_ids))
        return

    log.info("Scheduler started", registered_job_count=len(registered_ids))
    scheduler.start()


if __name__ == "__main__":
    main()
