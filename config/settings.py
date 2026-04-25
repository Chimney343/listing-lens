"""Application settings loaded from environment variables."""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Centralized runtime configuration for scraper, scheduler, and migrations."""

    env: Literal["development", "production"] = Field(
        default="development",
        alias="ENV",
    )
    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    photo_storage_backend: Literal["filesystem", "s3"] = Field(
        default="filesystem",
        alias="PHOTO_STORAGE_BACKEND",
    )
    photo_base_path: str = Field(default="/mnt/nvme/photos", alias="PHOTO_BASE_PATH")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    json_logs: bool = Field(default=False, alias="JSON_LOGS")
    pii_enabled: bool = Field(default=True, alias="PII_ENABLED")
    use_db_slug_queue: bool = Field(default=False, alias="USE_DB_SLUG_QUEUE")

    model_config = {
        "env_file": Path(__file__).resolve().parents[1] / ".env",
        "env_file_encoding": "utf-8-sig",
        "extra": "ignore",
        "populate_by_name": True,
    }

    def require_database_url(self, context: str = "runtime") -> str:
        """Return DATABASE_URL or raise a clear error for callers that need DB access."""

        if not self.database_url:
            raise RuntimeError(f"DATABASE_URL is required for {context}")
        return self.database_url

    @property
    def sqlalchemy_database_url(self) -> str:
        """Return SQLAlchemy-compatible database URL for Alembic/SQLAlchemy tooling."""

        raw_url = self.require_database_url(context="sqlalchemy")
        if raw_url.startswith(("postgresql://", "postgres://")):
            return raw_url.replace("://", "+psycopg://", 1)
        return raw_url

    @property
    def database_host(self) -> str:
        """Extract hostname from the configured database URL for startup logging."""

        if not self.database_url:
            return "unset"
        parsed = urlparse(self.database_url)
        return parsed.hostname or "unknown"


settings = Settings()
