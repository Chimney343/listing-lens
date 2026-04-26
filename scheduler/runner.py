"""Execution helpers for running scheduled spider jobs."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone

from config.settings import settings
from logging_config import get_logger
from scheduler.config import SpiderJob, SpiderJobManifest
from scheduler.jobs import SCRAPY_DIR, build_spider_command


_log = get_logger(__name__)


def _default_correlation_id(job_id: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{job_id}-{timestamp}"


def _refresh_slug_queue_after_slug_job(*, job: SpiderJob, correlation_id: str) -> int:
    database_url = settings.require_database_url(
        context=f"scheduler job '{job.job_id}' slug queue refresh"
    )

    from storage import db as slug_storage

    conn = slug_storage.connect(database_url)
    try:
        return slug_storage.refresh_slug_queue(conn)
    finally:
        conn.close()


def run_job(
    *,
    job: SpiderJob,
    manifest: SpiderJobManifest,
    correlation_id: str | None = None,
) -> int:
    """Run a single scheduled spider job through scrapy CLI."""

    effective_correlation_id = correlation_id or _default_correlation_id(job.job_id)
    command = build_spider_command(
        job=job,
        manifest=manifest,
        correlation_id=effective_correlation_id,
    )

    _log.info(
        "Scheduled job started",
        job_id=job.job_id,
        portal=job.portal,
        spider_kind=job.spider_kind,
        correlation_id=effective_correlation_id,
    )

    result = subprocess.run(command, cwd=SCRAPY_DIR)

    if result.returncode != 0:
        _log.error(
            "Scheduled job failed",
            job_id=job.job_id,
            portal=job.portal,
            spider_kind=job.spider_kind,
            return_code=result.returncode,
            correlation_id=effective_correlation_id,
        )
        raise RuntimeError(
            f"Scheduled job '{job.job_id}' failed with exit code {result.returncode}"
        )

    _log.info(
        "Scheduled job completed",
        job_id=job.job_id,
        portal=job.portal,
        spider_kind=job.spider_kind,
        return_code=result.returncode,
        correlation_id=effective_correlation_id,
    )

    if job.spider_kind == "slugs" and job.use_db_slug_queue:
        try:
            refreshed_rows = _refresh_slug_queue_after_slug_job(
                job=job,
                correlation_id=effective_correlation_id,
            )
        except Exception:
            _log.error(
                "Scheduled slug queue refresh failed",
                job_id=job.job_id,
                portal=job.portal,
                spider_kind=job.spider_kind,
                correlation_id=effective_correlation_id,
                exc_info=True,
            )
            raise

        _log.info(
            "Scheduled slug queue refreshed",
            job_id=job.job_id,
            portal=job.portal,
            spider_kind=job.spider_kind,
            refreshed_rows=refreshed_rows,
            correlation_id=effective_correlation_id,
        )

    return result.returncode
