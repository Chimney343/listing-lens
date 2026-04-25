"""Local chaining script: run otodom_slugs then feed slugs to otodom_detail.

Usage:
    poetry run python chain_otodom.py [options]

Options:
    --city              City slug (default: from otodom_config.json)
    --voivodeship       Voivodeship slug
    --powiat            Powiat slug
    --gmina             Gmina slug
    --property-type     Property type (mieszkanie, dom, etc.)
    --districts         Comma-separated district slugs
    --price-min         Minimum price in PLN
    --price-max         Maximum price in PLN
    --area-min          Minimum area in m2
    --area-max          Maximum area in m2
    --terrain-area-min  Minimum terrain area in m2
    --terrain-area-max  Maximum terrain area in m2
    --price-per-meter-min  Minimum price per meter in PLN
    --price-per-meter-max  Maximum price per meter in PLN
    --build-year-min    Minimum build year
    --build-year-max    Maximum build year
    --rooms-number      Comma-separated room categories (e.g. ONE,TWO)
    --building-material Comma-separated building material categories
    --extras            Comma-separated extras categories
    --max-pages         Cap slug collection at N pages (default: unlimited)
    --config-file       Path to otodom_config.json (default: otodom_config.json)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


DATA_DIR = Path(__file__).parent / "data" / "otodom"
SCRAPY_DIR = Path(__file__).parent / "scrapy_project"


def _run_spider(spider_name: str, args: list[str]) -> int:
    cmd = ["poetry", "run", "scrapy", "crawl", spider_name] + args
    result = subprocess.run(cmd, cwd=SCRAPY_DIR)
    return result.returncode


def _latest_run_dir() -> Path | None:
    """Return the most recent slug-collection run directory."""
    _DATE_DIR = re.compile(r"^\d{8}_\d{6}(?:_slugs)?$")
    dirs = sorted(
        (
            d
            for d in DATA_DIR.iterdir()
            if d.is_dir()
            and _DATE_DIR.match(d.name)
            and (d / "slug_collection.jsonl").exists()
        ),
        key=lambda d: d.name,
        reverse=True,
    )
    return dirs[0] if dirs else None


def _read_run_city(run_dir: Path) -> str | None:
    """Read the city recorded by the slug spider, if available."""
    meta_file = run_dir / "slug_run_meta.jsonl"
    if not meta_file.exists():
        return None

    with open(meta_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            city = record.get("city")
            if city:
                return str(city)

    return None


def _read_run_id(run_dir: Path) -> str | None:
    """Read slug run ID from slug_run_meta.jsonl if available."""
    meta_file = run_dir / "slug_run_meta.jsonl"
    if not meta_file.exists():
        return None

    with open(meta_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            run_id = record.get("run_id")
            if run_id:
                return str(run_id)

    return None


def _read_run_use_db_slug_queue(run_dir: Path) -> bool:
    """Read DB handoff flag from slug_run_meta.jsonl if present."""
    meta_file = run_dir / "slug_run_meta.jsonl"
    if not meta_file.exists():
        return False

    with open(meta_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            parameters = record.get("parameters") or {}
            raw_flag = parameters.get("use_db_slug_queue", False)
            if isinstance(raw_flag, bool):
                return raw_flag
            return str(raw_flag).strip().lower() not in {"0", "false", "", "no", "off"}

    return False


def _refresh_db_slug_queue() -> int:
    """Refresh the operational slugs queue from raw slug observations."""
    from config.settings import settings

    database_url = settings.require_database_url(context="chain_otodom DB slug handoff")

    from storage import db as storage_db

    conn = storage_db.connect(database_url)
    try:
        return storage_db.refresh_slug_queue(conn)
    finally:
        conn.close()


def _read_slugs(run_dir: Path) -> list[str]:
    """
    Extract slug list from slug_collection.jsonl in run_dir (for count reporting only).
    
    Args:
        run_dir: Directory containing slug_collection.jsonl
        
    Returns:
        List of slugs found
        
    Raises:
        FileNotFoundError: If slug_collection.jsonl doesn't exist
        ValueError: If no slugs found in file
        json.JSONDecodeError: If file contains invalid JSON
    """
    output_file = run_dir / "slug_collection.jsonl"
    if not output_file.exists():
        raise FileNotFoundError(f"Slug collection file not found: {output_file}")
    
    slugs: list[str] = []
    with open(output_file, encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as e:
                raise json.JSONDecodeError(
                    f"Invalid JSON at line {line_num} in {output_file}",
                    e.doc, e.pos
                ) from e
            
            slug = record.get("slug")
            if slug:
                slugs.append(slug)
    
    if not slugs:
        raise ValueError(f"No slug records found in {output_file}")
    
    return slugs


def main() -> None:
    parser = argparse.ArgumentParser(description="Chain otodom_slugs → otodom_detail")
    parser.add_argument("--city", default="")
    parser.add_argument("--voivodeship", default="")
    parser.add_argument("--powiat", default="")
    parser.add_argument("--gmina", default="")
    parser.add_argument("--property-type", default="")
    parser.add_argument("--districts", default="")
    parser.add_argument("--price-min", default="")
    parser.add_argument("--price-max", default="")
    parser.add_argument("--area-min", default="")
    parser.add_argument("--area-max", default="")
    parser.add_argument("--terrain-area-min", default="")
    parser.add_argument("--terrain-area-max", default="")
    parser.add_argument("--price-per-meter-min", default="")
    parser.add_argument("--price-per-meter-max", default="")
    parser.add_argument("--build-year-min", default="")
    parser.add_argument("--build-year-max", default="")
    parser.add_argument("--rooms-number", default="")
    parser.add_argument("--building-material", default="")
    parser.add_argument("--extras", default="")
    parser.add_argument("--max-pages", default="")
    parser.add_argument("--config-file", default="")
    opts = parser.parse_args()

    # ── Phase 1: collect slugs ────────────────────────────────────────────────
    slug_args: list[str] = []
    for name, val in [
        ("city", opts.city),
        ("voivodeship", opts.voivodeship),
        ("powiat", opts.powiat),
        ("gmina", opts.gmina),
        ("property_type", opts.property_type),
        ("districts", opts.districts),
        ("price_min", opts.price_min),
        ("price_max", opts.price_max),
        ("area_min", opts.area_min),
        ("area_max", opts.area_max),
        ("terrain_area_min", opts.terrain_area_min),
        ("terrain_area_max", opts.terrain_area_max),
        ("price_per_meter_min", opts.price_per_meter_min),
        ("price_per_meter_max", opts.price_per_meter_max),
        ("build_year_min", opts.build_year_min),
        ("build_year_max", opts.build_year_max),
        ("rooms_number", opts.rooms_number),
        ("building_material", opts.building_material),
        ("extras", opts.extras),
        ("max_pages", opts.max_pages),
        ("config_file", opts.config_file),
    ]:
        if val:
            slug_args += ["-a", f"{name}={val}"]

    print("[chain] Running otodom_slugs …")
    rc = _run_spider("otodom_slugs", slug_args)
    if rc != 0:
        print(f"[chain] otodom_slugs exited with code {rc}", file=sys.stderr)
        sys.exit(rc)

    # ── Locate slug output ────────────────────────────────────────────────────
    run_dir = _latest_run_dir()
    if run_dir is None:
        print("[chain] ERROR: no run directories found under data/otodom/", file=sys.stderr)
        sys.exit(1)

    try:
        slugs = _read_slugs(run_dir)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
        print(f"[chain] ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[chain] Collected {len(slugs)} slugs from {run_dir.name}")
    run_id = _read_run_id(run_dir)

    # ── Phase 2: scrape details ───────────────────────────────────────────────
    use_db_slug_queue = _read_run_use_db_slug_queue(run_dir)
    if use_db_slug_queue:
        from config.settings import settings

        print(
            f"[chain] DB handoff enabled (env={settings.env}, db_host={settings.database_host})"
        )
        try:
            refreshed_rows = _refresh_db_slug_queue()
            print(f"[chain] Refreshed slug queue in DB ({refreshed_rows} rows)")
        except Exception as e:
            print(f"[chain] ERROR: failed to refresh DB slug queue: {e}", file=sys.stderr)
            sys.exit(1)
        detail_args = ["-a", "use_db_slug_queue=1"]
    else:
        # Pass slug_collection file directly for file-based handoff.
        slug_collection_file = str(run_dir / "slug_collection.jsonl")
        detail_args = ["-a", f"slug_collection_file={slug_collection_file}"]

    detail_city = opts.city or _read_run_city(run_dir)
    if detail_city:
        detail_args += ["-a", f"city={detail_city}"]

    if run_id:
        detail_args += ["-a", f"correlation_id={run_id}"]

    print(f"[chain] Running otodom_detail for {len(slugs)} slugs …")
    rc = _run_spider("otodom_detail", detail_args)
    if rc != 0:
        print(f"[chain] otodom_detail exited with code {rc}", file=sys.stderr)
        sys.exit(rc)

    print("[chain] Done.")


if __name__ == "__main__":
    main()
