"""Local chaining script: run otodom_slugs then feed slugs to otodom_detail.

Usage:
    poetry run python chain_otodom.py [options]

Options:
    --city              City slug (default: from otodom_config.json)
    --voivodeship       Voivodeship slug
    --powiat            Powiat slug
    --gmina             Gmina slug
    --property-type     Property type (mieszkanie, dom, etc.)
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

    # ── Phase 2: scrape details ───────────────────────────────────────────────
    # Pass the slug_collection.jsonl path directly — OtodomDetailSpider reads SlugCollectionItem records.
    slug_collection_file = str(run_dir / "slug_collection.jsonl")
    detail_args = ["-a", f"slug_collection_file={slug_collection_file}"]
    detail_city = opts.city or _read_run_city(run_dir)
    if detail_city:
        detail_args += ["-a", f"city={detail_city}"]

    print(f"[chain] Running otodom_detail for {len(slugs)} slugs …")
    rc = _run_spider("otodom_detail", detail_args)
    if rc != 0:
        print(f"[chain] otodom_detail exited with code {rc}", file=sys.stderr)
        sys.exit(rc)

    print("[chain] Done.")


if __name__ == "__main__":
    main()
