---
applyTo: "**/scheduler/**,**/jobs.py,**/freshness*,**/main.py"
---

# Stage 4 — Freshness & Re-check Strategy

## Objective

Implement tiered re-check schedules, detect price changes, mark listings as gone (multi-check confirmation). Use APScheduler for scheduling. Invoke Scrapy spiders via subprocess to avoid Twisted reactor issues.

## Dependencies

```
apscheduler>=3.11
httpx>=0.27    # for lightweight freshness checks (no full Scrapy needed)
```

## Tiered Re-check Frequency

| Tier       | Listing Age        | Re-check Interval | Rationale                            |
| ---------- | ------------------ | ------------------ | ------------------------------------ |
| **New**    | < 3 days           | Every 24 hours     | Most dynamic: price may change fast  |
| **Active** | 3 days – 3 weeks   | Every 2-3 days     | Stable but still on market           |
| **Stale**  | > 3 weeks          | Every 7 days       | Likely overpriced; low priority      |

## Gone Detection

**Never mark gone on first failure.** Portals have outages, CDN issues, rate limits.

```python
GONE_THRESHOLD = 3  # confirmed absent this many times → mark gone

async def check_listing_freshness(db, listing_hash: str):
    listing = db.get_listing_by_hash(listing_hash)
    sources = db.get_sources_for_listing(listing_hash)
    
    any_alive = False
    for source in sources:
        alive, price = await check_single_url(source["source_url"], source["source_portal"])
        if alive:
            any_alive = True
            db.update_source_last_seen(source["id"])
            if price and price != source["price_at_source"]:
                db.record_price_change(listing_hash, price, None, source["source_portal"])
                db.update_source_price(source["id"], price)
        else:
            db.mark_source_inactive(source["id"])
    
    if any_alive:
        db.update_listing_last_seen(listing_hash)
        db.reset_gone_count(listing_hash)
    else:
        count = listing["gone_check_count"] + 1
        db.increment_gone_count(listing_hash)
        if count >= GONE_THRESHOLD:
            db.mark_listing_gone(listing_hash)
```

**Freshness checks use `httpx` directly** — not Scrapy. These are lightweight HEAD/GET checks on known URLs. No need for full spider infrastructure. Use `scrapy-impersonate`-style headers though:

```python
import httpx, random

HEADERS = {
    "Accept-Language": "pl-PL,pl;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0",
]

async def check_single_url(url: str, portal: str) -> tuple[bool, int | None]:
    headers = {**HEADERS, "User-Agent": random.choice(UA_POOL)}
    async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
        try:
            resp = await client.get(url, follow_redirects=True)
            if resp.status_code in (404, 410):
                return False, None
            if is_soft_404(resp.text, portal):
                return False, None
            price = extract_current_price(resp.text, portal)
            return True, price
        except (httpx.TimeoutException, httpx.ConnectError):
            return True, None  # assume alive on network error
```

## APScheduler Configuration

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import subprocess, asyncio

def create_scheduler(db) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Europe/Warsaw")
    
    # JOB 1: Full scrape — daily at 03:00
    # Invokes Scrapy spiders via subprocess to avoid reactor conflicts
    scheduler.add_job(
        run_all_spiders, CronTrigger(hour=3, minute=0),
        id="full_scrape", max_instances=1, misfire_grace_time=3600,
    )
    
    # JOB 2: Freshness check (new) — daily at 10:00
    scheduler.add_job(
        run_freshness, CronTrigger(hour=10, minute=0),
        kwargs={"db": db, "tier": "new"},
        id="fresh_new", max_instances=1,
    )
    
    # JOB 3: Freshness check (active) — every 2 days at 14:00
    scheduler.add_job(
        run_freshness, CronTrigger(day="*/2", hour=14, minute=0),
        kwargs={"db": db, "tier": "active"},
        id="fresh_active", max_instances=1,
    )
    
    # JOB 4: Freshness check (stale) — weekly Sunday 06:00
    scheduler.add_job(
        run_freshness, CronTrigger(day_of_week="sun", hour=6, minute=0),
        kwargs={"db": db, "tier": "stale"},
        id="fresh_stale", max_instances=1,
    )
    
    # JOB 5: Score unscored listings — daily at 08:00
    scheduler.add_job(
        run_scoring, CronTrigger(hour=8, minute=0),
        kwargs={"db": db},
        id="scoring", max_instances=1,
    )
    
    return scheduler


def run_all_spiders():
    """Run each Scrapy spider as a subprocess. Avoids Twisted reactor issues."""
    for spider in ["otodom", "gratka", "morizon"]:
        result = subprocess.run(
            ["scrapy", "crawl", spider, "-s", "HTTPCACHE_ENABLED=False"],
            capture_output=True, text=True, timeout=3600,
        )
        if result.returncode != 0:
            print(f"Spider {spider} failed: {result.stderr[-500:]}")


async def run_freshness(db, tier: str):
    listings = db.get_listings_for_recheck(tier)
    for listing in listings:
        await check_listing_freshness(db, listing["listing_hash"])
        await asyncio.sleep(random.uniform(2.0, 4.0))


async def run_scoring(db):
    """Implemented in Stage 5."""
    pass
```

## Known Fragility Points

1. **Twisted reactor single-run**: `CrawlerProcess.start()` calls `reactor.run()` which cannot be called twice. The subprocess approach avoids this entirely. Do not try to run multiple Scrapy crawls in-process sequentially.
2. **APScheduler timezone**: Explicitly set `Europe/Warsaw`. Forgetting this means jobs fire at UTC times, which shifts scraping to daytime hours (higher chance of detection).
3. **Freshness check rate limiting**: The `check_single_url` function uses `httpx` directly without scrapy-impersonate's TLS spoofing. If portals start blocking these checks, wrap them in a minimal Scrapy spider or add proxy rotation to the httpx client.
4. **`misfire_grace_time`**: Set to 3600 (1 hour) for scraping jobs. If the scheduler was down and missed a job's scheduled time, it'll still fire if within 1 hour. Without this, missed jobs are silently skipped.

## Deployment

### Systemd Unit File (VPS)
```ini
[Unit]
Description=Property Pipeline Scheduler
After=network.target

[Service]
Type=simple
User=property
WorkingDirectory=/opt/property-pipeline
ExecStart=/opt/property-pipeline/.venv/bin/python main.py
Restart=always
RestartSec=30
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

## Testing

1. Trigger `run_all_spiders()` manually → verify each spider runs as subprocess and returns 0
2. Insert a listing, run freshness check → verify `last_seen` updated
3. Simulate removed listing (3 checks) → verify `is_active` set to False
4. Change price on portal → verify new `price_history` row inserted
5. Verify scheduler jobs are registered: `scheduler.get_jobs()`
