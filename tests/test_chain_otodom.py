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


def test_read_run_use_db_slug_queue_reads_slug_run_meta(tmp_path):
    run_dir = tmp_path / "20260328_120000_slugs"
    run_dir.mkdir()
    (run_dir / "slug_run_meta.jsonl").write_text(
        json.dumps({"parameters": {"use_db_slug_queue": True}}) + "\n",
        encoding="utf-8",
    )

    assert chain_otodom._read_run_use_db_slug_queue(run_dir) is True


def test_read_run_use_db_slug_queue_defaults_false(tmp_path):
    run_dir = tmp_path / "20260328_120000_slugs"
    run_dir.mkdir()
    (run_dir / "slug_run_meta.jsonl").write_text(
        json.dumps({"city": "krakow"}) + "\n",
        encoding="utf-8",
    )

    assert chain_otodom._read_run_use_db_slug_queue(run_dir) is False


def test_read_run_id_reads_slug_run_meta(tmp_path):
    run_dir = tmp_path / "20260328_120000_slugs"
    run_dir.mkdir()
    (run_dir / "slug_run_meta.jsonl").write_text(
        json.dumps({"run_id": "run-123"}) + "\n",
        encoding="utf-8",
    )

    assert chain_otodom._read_run_id(run_dir) == "run-123"


def test_main_uses_slug_collection_file_when_db_handoff_disabled(tmp_path, monkeypatch):
    run_dir = tmp_path / "20260328_120000_slugs"
    run_dir.mkdir()

    calls: list[tuple[str, list[str]]] = []

    def fake_run_spider(spider_name: str, args: list[str]) -> int:
        calls.append((spider_name, args))
        return 0

    monkeypatch.setattr(chain_otodom, "_run_spider", fake_run_spider)
    monkeypatch.setattr(chain_otodom, "_latest_run_dir", lambda: run_dir)
    monkeypatch.setattr(chain_otodom, "_read_slugs", lambda _run_dir: ["slug-a", "slug-b"])
    monkeypatch.setattr(chain_otodom, "_read_run_city", lambda _run_dir: "krakow")
    monkeypatch.setattr(chain_otodom, "_read_run_id", lambda _run_dir: "run-123", raising=False)
    monkeypatch.setattr(chain_otodom, "_read_run_use_db_slug_queue", lambda _run_dir: False)
    monkeypatch.setattr(
        chain_otodom,
        "_refresh_db_slug_queue",
        lambda: (_ for _ in ()).throw(AssertionError("refresh should not be called")),
    )
    monkeypatch.setattr("sys.argv", ["chain_otodom.py"])

    chain_otodom.main()

    assert len(calls) == 2
    detail_args = calls[1][1]
    assert calls[1][0] == "otodom_detail"
    assert any(
        arg.startswith("slug_collection_file=")
        for arg in detail_args
        if not arg.startswith("-a")
    )
    assert "correlation_id=run-123" in detail_args
    assert all("use_db_slug_queue=1" not in arg for arg in detail_args)


def test_main_uses_db_handoff_when_enabled(tmp_path, monkeypatch):
    run_dir = tmp_path / "20260328_120000_slugs"
    run_dir.mkdir()

    calls: list[tuple[str, list[str]]] = []
    refreshed = {"called": False}

    def fake_run_spider(spider_name: str, args: list[str]) -> int:
        calls.append((spider_name, args))
        return 0

    def fake_refresh() -> int:
        refreshed["called"] = True
        return 3

    monkeypatch.setattr(chain_otodom, "_run_spider", fake_run_spider)
    monkeypatch.setattr(chain_otodom, "_latest_run_dir", lambda: run_dir)
    monkeypatch.setattr(chain_otodom, "_read_slugs", lambda _run_dir: ["slug-a", "slug-b"])
    monkeypatch.setattr(chain_otodom, "_read_run_city", lambda _run_dir: "krakow")
    monkeypatch.setattr(chain_otodom, "_read_run_id", lambda _run_dir: "run-123", raising=False)
    monkeypatch.setattr(chain_otodom, "_read_run_use_db_slug_queue", lambda _run_dir: True)
    monkeypatch.setattr(chain_otodom, "_refresh_db_slug_queue", fake_refresh)
    monkeypatch.setattr("sys.argv", ["chain_otodom.py"])

    chain_otodom.main()

    assert refreshed["called"] is True
    assert len(calls) == 2
    detail_args = calls[1][1]
    assert calls[1][0] == "otodom_detail"
    assert "use_db_slug_queue=1" in detail_args
    assert "correlation_id=run-123" in detail_args
    assert all("slug_collection_file=" not in arg for arg in detail_args)


def test_main_passes_full_filter_args_to_slug_spider(tmp_path, monkeypatch):
    run_dir = tmp_path / "20260328_120000_slugs"
    run_dir.mkdir()

    calls: list[tuple[str, list[str]]] = []

    def fake_run_spider(spider_name: str, args: list[str]) -> int:
        calls.append((spider_name, args))
        return 0

    monkeypatch.setattr(chain_otodom, "_run_spider", fake_run_spider)
    monkeypatch.setattr(chain_otodom, "_latest_run_dir", lambda: run_dir)
    monkeypatch.setattr(chain_otodom, "_read_slugs", lambda _run_dir: ["slug-a"])
    monkeypatch.setattr(chain_otodom, "_read_run_city", lambda _run_dir: "mielec")
    monkeypatch.setattr(chain_otodom, "_read_run_id", lambda _run_dir: "run-123", raising=False)
    monkeypatch.setattr(chain_otodom, "_read_run_use_db_slug_queue", lambda _run_dir: False)
    monkeypatch.setattr(
        "sys.argv",
        [
            "chain_otodom.py",
            "--city", "mielec",
            "--voivodeship", "podkarpackie",
            "--powiat", "mielecki",
            "--gmina", "gmina-miejska--mielec",
            "--property-type", "dom",
            "--price-min", "5000",
            "--price-max", "100000",
            "--area-min", "25",
            "--area-max", "50",
            "--terrain-area-min", "50",
            "--terrain-area-max", "100",
            "--price-per-meter-min", "5000",
            "--price-per-meter-max", "10000",
            "--build-year-min", "1950",
            "--build-year-max", "2025",
            "--rooms-number", "ONE,TWO,THREE,FIVE,FOUR",
            "--building-material", "BRICK",
            "--extras", "IS_BUNGALOV,HAS_PHOTOS",
            "--max-pages", "1",
        ],
    )

    chain_otodom.main()

    slug_args = calls[0][1]
    assert calls[0][0] == "otodom_slugs"
    assert "city=mielec" in slug_args
    assert "voivodeship=podkarpackie" in slug_args
    assert "powiat=mielecki" in slug_args
    assert "gmina=gmina-miejska--mielec" in slug_args
    assert "property_type=dom" in slug_args
    assert "price_min=5000" in slug_args
    assert "price_max=100000" in slug_args
    assert "area_min=25" in slug_args
    assert "area_max=50" in slug_args
    assert "terrain_area_min=50" in slug_args
    assert "terrain_area_max=100" in slug_args
    assert "price_per_meter_min=5000" in slug_args
    assert "price_per_meter_max=10000" in slug_args
    assert "build_year_min=1950" in slug_args
    assert "build_year_max=2025" in slug_args
    assert "rooms_number=ONE,TWO,THREE,FIVE,FOUR" in slug_args
    assert "building_material=BRICK" in slug_args
    assert "extras=IS_BUNGALOV,HAS_PHOTOS" in slug_args
    assert "max_pages=1" in slug_args