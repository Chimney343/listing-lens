---
applyTo: "**/*.py"
---

# Logging & Observability

## Overview

Structured logging is implemented in `logging_config.py` at the project root
using `structlog` backed by the standard `logging` module. All pipeline
components — spiders, pipelines, schedulers, scorers — import from this shared
module.

The module provides:
- `configure_logging()` — call once at process startup to set up handlers and
  structlog processors.
- `get_logger(name)` — returns a bound `structlog.stdlib.BoundLogger`.
- `set_correlation_id(cid?)` — binds a correlation ID to the current
  `contextvars` context and returns it (generates a UUID if none given).
- `get_correlation_id()` — reads current correlation ID.
- `clear_correlation_id()` — clears all structlog context vars.

---

## Scrapy Integration

`settings.py` calls `configure_logging()` at module load time:

```python
from logging_config import configure_logging

configure_logging(
    log_level=LOG_LEVEL,
    log_dir=LOG_DIR,
    json_format=False,   # set True in production
    enable_file_logging=True,
)
```

`LOG_DIR` resolves to `logs/` at the project root. Logs rotate daily at
midnight; 7 days are retained, compressed with gzip.

---

## How to Log in Any Module

```python
import structlog

logger = structlog.get_logger(__name__)

# Informational event with structured context
logger.info("listing_scraped", url=item["source_url"], portal=item["source_portal"])

# Warning — recoverable anomaly
logger.warning("photo_fetch_failed", url=photo_url, listing_id=listing_id)

# Error with exception info
try:
    process(item)
except Exception:
    logger.error("processing_failed", listing_url=item.get("source_url"), exc_info=True)
```

**Never** use f-strings as the log message. The first argument is an event
key; structured fields go as keyword arguments.

---

## Log Levels

| Level     | Use for                                                |
|-----------|--------------------------------------------------------|
| `DEBUG`   | Internal state, per-request detail (dev only)          |
| `INFO`    | Lifecycle events: spider start/end, item counts, writes|
| `WARNING` | Recoverable anomalies: retries, missing optional data  |
| `ERROR`   | Failures needing attention: parse errors, DB errors    |

The console handler shows `INFO` and above. `DEBUG` goes to the file only.

---

## Correlation IDs

Correlation IDs link log lines for a single spider run or request across
components. Set one at the start of each logical unit of work:

```python
from logging_config import set_correlation_id, clear_correlation_id

# At spider open or job start:
run_id = set_correlation_id()   # auto-generates UUID
logger.info("spider_opened", spider=spider.name, run_id=run_id)

# At spider close:
clear_correlation_id()
```

Once set, `structlog` automatically includes `correlation_id` in every
subsequent log line from that context without manual passing.

> **TODO (Stage 4)**: Add a Scrapy downloader middleware in `middlewares.py`
> that calls `set_correlation_id()` on `spider_opened` and
> `clear_correlation_id()` on `spider_closed`, so all spiders get correlation
> IDs automatically without per-spider boilerplate.

---

## Log Files

```
logs/
├── application.log              # current combined log
└── application.log.YYYY-MM-DD.gz  # archived (7-day retention, gzip)
```

Spider-specific log files are not currently created; all output goes to
`application.log`. Per-spider files can be added by passing a named file
handler to `configure_logging()` if needed.

---

## Configuration Parameters

| Parameter            | Default | Notes                              |
|----------------------|---------|------------------------------------|
| `log_level`          | `INFO`  | Set `DEBUG` locally for verbosity  |
| `log_dir`            | `None`  | `None` → stdout only               |
| `json_format`        | `False` | Set `True` in production           |
| `enable_file_logging`| `True`  | Only active when `log_dir` is set  |

In production, set `json_format=True` (or pass via env) to emit machine-readable
JSON lines queryable by Loki/Grafana.
