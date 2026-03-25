---
applyTo: "**/*.py"
---

# Logging & Observability Strategy

## Objective

Implement structured, production-ready logging across the property pipeline with:
- **Structured logging** (JSON format) for machine readability and querying
- **Automatic log rotation** with 7-day retention
- **Correlation IDs** to trace requests across components
- **Consistent log levels** following semantic conventions
- **Centralized configuration** for easy maintenance

## Dependencies

Add the following dependencies to `pyproject.toml`:

```toml
dependencies = [
    # ... existing dependencies ...
    "structlog>=24.0.0",
    "structlog[dev]>=24.0.0",  # For development processors
]
```

## Logging Configuration Module

Create `scrapy_project/property_scraper/logging_config.py`:

```python
"""
Centralized logging configuration for the property pipeline.
Configures structlog for structured logging with JSON output in production
and human-readable output in development.
"""

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional

import structlog
from structlog.contextvars import merge_contextvars, clear_contextvars


def configure_logging(
    log_level: str = "INFO",
    log_dir: Optional[Path] = None,
    json_format: bool = False,
    enable_file_logging: bool = True,
) -> None:
    """
    Configure structured logging for the application.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_dir: Directory for log files. If None, logs go to stdout only.
        json_format: Use JSON format for logs (True for production)
        enable_file_logging: Enable file logging with rotation
    """
    # Ensure log directory exists
    if log_dir and enable_file_logging:
        log_dir.mkdir(parents=True, exist_ok=True)
    
    # Standard logging configuration
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level.upper()),
        handlers=[]  # We'll add handlers below
    )
    
    # Remove default handlers
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    if json_format:
        console_formatter = logging.Formatter("%(message)s")
    else:
        console_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # File handler with rotation (7-day retention)
    if log_dir and enable_file_logging:
        # Application log
        app_log_path = log_dir / "application.log"
        file_handler = logging.handlers.TimedRotatingFileHandler(
            filename=app_log_path,
            when="midnight",
            interval=1,
            backupCount=7,
            encoding="utf-8",
        )
        file_handler.setFormatter(console_formatter)
        root_logger.addHandler(file_handler)
        
        # Optional: Add compression for archived logs
        import gzip
        def namer(name):
            return name + ".gz"
        
        def rotator(source, dest):
            with open(source, "rb") as f_in:
                with gzip.open(dest, "wb") as f_out:
                    f_out.writelines(f_in)
            Path(source).unlink()
        
        file_handler.namer = namer
        file_handler.rotator = rotator
    
    # Structlog configuration
    processors = [
        merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    
    if json_format:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.processors.KeyValueRenderer(
            key_order=["timestamp", "level", "logger", "event"],
            drop_missing=True,
        ))
    
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance."""
    return structlog.get_logger(name)


# Context management for correlation IDs
from contextvars import ContextVar
import uuid

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def set_correlation_id(cid: Optional[str] = None) -> str:
    """
    Set correlation ID for current context.
    
    Args:
        cid: Correlation ID to use. If None, generates a new UUID.
    
    Returns:
        The correlation ID.
    """
    cid = cid or str(uuid.uuid4())
    _correlation_id.set(cid)
    structlog.contextvars.bind_contextvars(correlation_id=cid)
    return cid


def get_correlation_id() -> str:
    """Get current correlation ID."""
    return _correlation_id.get()


def clear_correlation_id() -> None:
    """Clear correlation ID from context."""
    clear_contextvars()
    _correlation_id.set("")
```

## Scrapy Integration

Update `scrapy_project/property_scraper/settings.py`:

```python
# Add to settings.py
import sys
from pathlib import Path

# Configure logging
LOG_LEVEL = "INFO"
LOG_ENCODING = "utf-8"

# Create logs directory
LOG_DIR = Path(__file__).resolve().parents[2] / "logs"

# Import and configure our logging
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from logging_config import configure_logging
    configure_logging(
        log_level=LOG_LEVEL,
        log_dir=LOG_DIR,
        json_format=False,  # Set to True in production
        enable_file_logging=True,
    )
except ImportError:
    pass  # Fall back to Scrapy's default logging

# Scrapy log configuration
LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
LOG_DATEFORMAT = "%Y-%m-%d %H:%M:%S"
```

## Scrapy Middleware for Correlation IDs

Create `scrapy_project/property_scraper/middlewares/correlation_middleware.py`:

```python
"""
Scrapy middleware for correlation ID management.
"""

import uuid
from typing import Any, Optional

from scrapy import Spider, signals
from scrapy.http import Request, Response

from property_scraper.logging_config import set_correlation_id, get_correlation_id


class CorrelationMiddleware:
    """Middleware to manage correlation IDs across requests."""
    
    @classmethod
    def from_crawler(cls, crawler):
        """Create middleware instance from crawler."""
        middleware = cls()
        crawler.signals.connect(middleware.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(middleware.spider_closed, signal=signals.spider_closed)
        return middleware
    
    def spider_opened(self, spider: Spider) -> None:
        """Set correlation ID when spider opens."""
        # Generate a job ID for this spider run
        job_id = f"{spider.name}_{uuid.uuid4().hex[:8]}"
        set_correlation_id(job_id)
        spider.logger = spider.logger.bind(job_id=job_id, spider=spider.name)
        spider.logger.info("Spider opened", job_id=job_id)
    
    def spider_closed(self, spider: Spider) -> None:
        """Clear correlation ID when spider closes."""
        spider.logger.info("Spider closed")
    
    def process_request(self, request: Request, spider: Spider) -> Optional[Any]:
        """Add correlation ID to request headers."""
        correlation_id = get_correlation_id()
        if correlation_id:
            request.headers["X-Correlation-ID"] = correlation_id.encode()
        return None
    
    def process_response(self, request: Request, response: Response, spider: Spider) -> Response:
        """Extract correlation ID from response headers if present."""
        # You can log response correlation if needed
        return response
```

Update `scrapy_project/property_scraper/middlewares.py`:

```python
# Add to DOWNLOADER_MIDDLEWARES in settings.py
DOWNLOADER_MIDDLEWARES = {
    "property_scraper.middlewares.correlation_middleware.CorrelationMiddleware": 100,
    # ... existing middlewares ...
}
```

## Logging Best Practices

### 1. Log Levels

Use log levels consistently:

| Level | Purpose | Examples |
|-------|---------|----------|
| `DEBUG` | Development diagnostics | Variable values, internal state, HTTP request details |
| `INFO` | Request lifecycle, operations | Spider start/end, item counts, summary statistics |
| `WARNING` | Recoverable anomalies | Retries, rate limiting, missing optional data |
| `ERROR` | Failures needing attention | Failed requests, parsing errors, database errors |

### 2. Structured Logging Examples

```python
import structlog

logger = structlog.get_logger(__name__)

# Good: Structured logging with context
logger.info(
    "Listing processed",
    listing_id=item["listing_id"],
    source=item["source"],
    price=item["price_pln"],
    area=item["area_m2"],
    duration_ms=elapsed_ms,
)

# Good: Error logging with exception context
try:
    process_listing(item)
except Exception as e:
    logger.error(
        "Failed to process listing",
        listing_id=item.get("listing_id"),
        error_type=type(e).__name__,
        error_message=str(e),
        exc_info=True,  # Includes stack trace
    )
    raise

# Avoid: Unstructured logging
logger.info(f"Processed listing {item['listing_id']}")  # Not structured
```

### 3. Correlation ID Usage

```python
from property_scraper.logging_config import get_correlation_id

class MyPipeline:
    def process_item(self, item, spider):
        correlation_id = get_correlation_id()
        logger = structlog.get_logger(__name__).bind(
            correlation_id=correlation_id,
            spider=spider.name,
        )
        
        logger.info(
            "Pipeline processing",
            listing_id=item.get("listing_id"),
            pipeline_stage="validation",
        )
        return item
```

### 4. Context Managers for Timing

```python
from contextlib import contextmanager
import time
import structlog

logger = structlog.get_logger(__name__)

@contextmanager
def timed_operation(name: str, **context):
    """Context manager for timing and logging operations."""
    start = time.perf_counter()
    logger.debug("Operation started", operation=name, **context)
    
    try:
        yield
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.error(
            "Operation failed",
            operation=name,
            duration_ms=round(elapsed_ms, 2),
            error=str(e),
            **context,
        )
        raise
    else:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "Operation completed",
            operation=name,
            duration_ms=round(elapsed_ms, 2),
            **context,
        )

# Usage
with timed_operation("download_photos", listing_id=listing_id):
    download_photos(listing_id)
```

## Log File Management

### Directory Structure

```
logs/
├── application.log        # Current combined log
├── application.log.2025-03-18.gz  # Archived logs (7 days retention)
├── otodom.log            # Spider-specific logs (optional)
├── gratka.log
└── morizon.log
```

### Rotation Policy

- Logs rotate daily at midnight
- 7 days of logs retained
- Old logs compressed with gzip
- Compression reduces storage by ~90%

### Cleanup Script (Optional)

Create `scripts/cleanup_logs.py`:

```python
#!/usr/bin/env python3
"""
Clean up log files older than 7 days.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
RETENTION_DAYS = 7

def cleanup_old_logs():
    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
    
    for log_file in LOG_DIR.glob("*.log.*"):
        try:
            # Parse date from filename (application.log.2025-03-18.gz)
            parts = log_file.name.split(".")
            if len(parts) >= 3:
                date_str = parts[-2]  # Second to last part before extension
                file_date = datetime.strptime(date_str, "%Y-%m-%d")
                
                if file_date < cutoff:
                    log_file.unlink()
                    print(f"Deleted: {log_file}")
        except (ValueError, IndexError):
            continue

if __name__ == "__main__":
    cleanup_old_logs()
```

## Environment-Specific Configuration

### Development (.env.development)

```
LOG_LEVEL=DEBUG
LOG_FORMAT=pretty  # Human-readable
LOG_DIR=./logs
```

### Production (.env.production)

```
LOG_LEVEL=INFO
LOG_FORMAT=json    # Machine-readable JSON
LOG_DIR=/var/log/property-pipeline
```

## Monitoring and Alerting

### Key Metrics to Monitor

1. **Error Rate**: `ERROR` logs per minute
2. **Request Latency**: Duration of scraping operations
3. **Item Throughput**: Items processed per minute
4. **Memory Usage**: Log memory warnings

### Integration with Monitoring Tools

- **Loki/Grafana**: Query structured logs
- **Prometheus**: Collect metrics from log patterns
- **Sentry**: Error tracking and alerting

## Migration Checklist

1. [ ] Add `structlog` dependency to `pyproject.toml`
2. [ ] Create `logging_config.py` module
3. [ ] Update Scrapy settings to use new logging
4. [ ] Create correlation middleware
5. [ ] Update existing spiders to use structured logging
6. [ ] Update pipelines to use structured logging
7. [ ] Create logs directory and test rotation
8. [ ] Update documentation for new logging patterns

## Troubleshooting

### Common Issues

1. **No logs appearing**: Check `LOG_LEVEL` setting and handler configuration
2. **Log rotation not working**: Verify file permissions on log directory
3. **Missing correlation IDs**: Ensure middleware is properly registered
4. **JSON format issues**: Check structlog processor configuration

### Debug Commands

```bash
# Test logging configuration
poetry run python -c "from property_scraper.logging_config import configure_logging; configure_logging(); import logging; logging.getLogger('test').info('Test message')"

# View recent logs
tail -f logs/application.log

# Check log rotation
ls -la logs/*.gz | wc -l
```

## References

- [Structlog Documentation](https://www.structlog.org/)
- [Python Logging Cookbook](https://docs.python.org/3/howto/logging-cookbook.html)
- [Scrapy Logging Documentation](https://docs.scrapy.org/en/latest/topics/logging.html)
- [The Twelve-Factor App: Logs](https://12factor.net/logs)