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


def test_run_job_raises_on_nonzero_exit(monkeypatch):
    manifest = SpiderJobManifest.model_validate(_manifest_dict())
    job = manifest.jobs[0]

    def fake_run(_command, cwd=None):
        return types.SimpleNamespace(returncode=2)

    monkeypatch.setattr("scheduler.runner.subprocess.run", fake_run)

    with pytest.raises(RuntimeError, match="otodom-krakow-slugs"):
        run_job(job=job, manifest=manifest, correlation_id="job-run-2")
