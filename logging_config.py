"""
Centralized logging configuration for the property pipeline.
Configures structlog for structured logging with JSON output in production
and human-readable output in development.
"""

import gzip
import logging
import logging.handlers
import sys
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Optional

import structlog
from structlog.contextvars import clear_contextvars, merge_contextvars


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
    if log_dir and enable_file_logging:
        log_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level.upper()),
        handlers=[],
    )

    # Root logger accepts everything — handlers filter independently
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    # Console only shows INFO and above; DEBUG goes to file only
    console_handler.setLevel(getattr(logging, log_level.upper()))
    if json_format:
        console_formatter = logging.Formatter("%(message)s")
    else:
        console_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    if log_dir and enable_file_logging:
        app_log_path = log_dir / "application.log"
        file_handler = logging.handlers.TimedRotatingFileHandler(
            filename=app_log_path,
            when="midnight",
            interval=1,
            backupCount=7,
            encoding="utf-8",
        )
        file_handler.setFormatter(console_formatter)

        def _namer(name: str) -> str:
            return name + ".gz"

        def _rotator(source: str, dest: str) -> None:
            with open(source, "rb") as f_in, gzip.open(dest, "wb") as f_out:
                f_out.writelines(f_in)
            Path(source).unlink()

        file_handler.namer = _namer
        file_handler.rotator = _rotator
        root_logger.addHandler(file_handler)

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
        processors.append(
            structlog.processors.KeyValueRenderer(
                key_order=["timestamp", "level", "logger", "event"],
                drop_missing=True,
            )
        )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance."""
    return structlog.get_logger(name)


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
