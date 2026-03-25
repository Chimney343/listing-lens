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
    """Return the most recently created otodom run directory (YYYYMMDD_HHMMSS)."""
    _DATE_DIR = re.compile(r"^\d{8}_\d{6}$")
    dirs = sorted(
        (d for d in DATA_DIR.iterdir() if d.is_dir() and _DATE_DIR.match(d.name)),
        key=lambda d: d.name,
        reverse=True,
    )
    return dirs[0] if dirs else None


def _read_slugs(run_dir: Path) -> list[str]:
    """Extract slug list from slug_collection.jsonl in run_dir (for count reporting only)."""    
    output_file = run_dir / "slug_collection.jsonl"
    if not output_file.exists():
        print(f"[chain] ERROR: {output_file} not found", file=sys.stderr)
        return []
    slugs: list[str] = []
    with open(output_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            slug = record.get("slug")
            if slug:
                slugs.append(slug)
    if not slugs:
        print(f"[chain] ERROR: no slug records found in {output_file}", file=sys.stderr)
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

    slugs = _read_slugs(run_dir)
    if not slugs:
        print("[chain] No slugs collected — nothing to detail-scrape.")
        sys.exit(0)

    print(f"[chain] Collected {len(slugs)} slugs from {run_dir.name}")

    # ── Phase 2: scrape details ───────────────────────────────────────────────
    # Pass the slug_collection.jsonl path directly — OtodomDetailSpider reads SlugCollectionItem records.
    slug_collection_file = str(run_dir / "slug_collection.jsonl")
    detail_args = ["-a", f"slug_collection_file={slug_collection_file}"]
    if opts.city:
        detail_args += ["-a", f"city={opts.city}"]

    print(f"[chain] Running otodom_detail for {len(slugs)} slugs …")
    rc = _run_spider("otodom_detail", detail_args)
    if rc != 0:
        print(f"[chain] otodom_detail exited with code {rc}", file=sys.stderr)
        sys.exit(rc)

    print("[chain] Done.")


if __name__ == "__main__":
    main()
