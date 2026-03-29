"""Tests for the local otodom chaining helper."""

from __future__ import annotations

import json

import chain_otodom


def test_latest_run_dir_accepts_slug_suffix(tmp_path, monkeypatch):
    latest_dir = tmp_path / "20260328_120000_slugs"
    older_dir = tmp_path / "20260327_235959_slugs"
    latest_dir.mkdir()
    older_dir.mkdir()
    (latest_dir / "slug_collection.jsonl").write_text("{}\n", encoding="utf-8")
    (older_dir / "slug_collection.jsonl").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(chain_otodom, "DATA_DIR", tmp_path)

    assert chain_otodom._latest_run_dir() == latest_dir


def test_read_run_city_reads_slug_run_meta(tmp_path):
    run_dir = tmp_path / "20260328_120000_slugs"
    run_dir.mkdir()
    (run_dir / "slug_run_meta.jsonl").write_text(
        json.dumps({"city": "krakow"}) + "\n",
        encoding="utf-8",
    )

    assert chain_otodom._read_run_city(run_dir) == "krakow"


def test_read_run_city_returns_none_when_meta_missing(tmp_path):
    run_dir = tmp_path / "20260328_120000_slugs"
    run_dir.mkdir()

    assert chain_otodom._read_run_city(run_dir) is None