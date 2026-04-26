"""Tests for scheduled job subprocess execution."""

from __future__ import annotations

import types

import pytest

from scheduler.config import SpiderJobManifest
from scheduler.runner import run_job


def _manifest_dict() -> dict:
    return {
        "search_profiles": {
            "krakow_core": {
                "city": "krakow",
                "voivodeship": "malopolskie",
                "powiat": "krakowski",
                "gmina": "gmina-miejska--krakow",
                "property_type": "mieszkanie",
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
                "use_db_slug_queue": False,
            }
        ],
    }


def test_run_job_invokes_subprocess(monkeypatch):
    manifest = SpiderJobManifest.model_validate(_manifest_dict())
    job = manifest.jobs[0]

    captured: dict[str, object] = {}

    def fake_run(command, cwd):
        captured["command"] = command
        captured["cwd"] = cwd
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr("scheduler.runner.subprocess.run", fake_run)

    return_code = run_job(job=job, manifest=manifest, correlation_id="job-run-1")

    assert return_code == 0
    assert captured["command"][:5] == ["poetry", "run", "scrapy", "crawl", "otodom_slugs"]
    assert "correlation_id=job-run-1" in captured["command"]


def test_run_slug_job_refreshes_queue_after_success(monkeypatch):
    payload = _manifest_dict()
    payload["jobs"][0]["use_db_slug_queue"] = True
    manifest = SpiderJobManifest.model_validate(payload)
    job = manifest.jobs[0]

    refresh_calls: list[tuple[str, str]] = []

    def fake_run(command, cwd):
        return types.SimpleNamespace(returncode=0)

    def fake_refresh(*, job, correlation_id):
        refresh_calls.append((job.job_id, correlation_id))
        return 7

    monkeypatch.setattr("scheduler.runner.subprocess.run", fake_run)
    monkeypatch.setattr(
        "scheduler.runner._refresh_slug_queue_after_slug_job",
        fake_refresh,
        raising=False,
    )

    return_code = run_job(job=job, manifest=manifest, correlation_id="job-run-3")

    assert return_code == 0
    assert refresh_calls == [("otodom-krakow-slugs", "job-run-3")]


def test_run_detail_job_does_not_refresh_queue(monkeypatch):
    manifest = SpiderJobManifest.model_validate(
        {
            "search_profiles": {"krakow_core": {"city": "krakow"}},
            "jobs": [
                {
                    "job_id": "otodom-krakow-detail",
                    "enabled": True,
                    "portal": "otodom",
                    "spider_kind": "detail",
                    "search_profile": "krakow_core",
                    "use_db_slug_queue": True,
                    "schedule": {"type": "interval", "hours": 12},
                }
            ],
        }
    )
    job = manifest.jobs[0]

    refresh_calls: list[str] = []

    def fake_run(command, cwd):
        return types.SimpleNamespace(returncode=0)

    def fake_refresh(*, job, correlation_id):
        refresh_calls.append(job.job_id)
        return 7

    monkeypatch.setattr("scheduler.runner.subprocess.run", fake_run)
    monkeypatch.setattr(
        "scheduler.runner._refresh_slug_queue_after_slug_job",
        fake_refresh,
        raising=False,
    )

    return_code = run_job(job=job, manifest=manifest, correlation_id="job-run-4")

    assert return_code == 0
    assert refresh_calls == []


def test_run_job_raises_on_nonzero_exit(monkeypatch):
    manifest = SpiderJobManifest.model_validate(_manifest_dict())
    job = manifest.jobs[0]

    def fake_run(_command, cwd=None):
        return types.SimpleNamespace(returncode=2)

    monkeypatch.setattr("scheduler.runner.subprocess.run", fake_run)

    with pytest.raises(RuntimeError, match="otodom-krakow-slugs"):
        run_job(job=job, manifest=manifest, correlation_id="job-run-2")
