from __future__ import annotations

import pytest

from config.settings import Settings


def test_settings_defaults_without_env_file() -> None:
    settings = Settings(_env_file=None)

    assert settings.env == "development"
    assert settings.log_level == "INFO"
    assert settings.json_logs is False
    assert settings.use_db_slug_queue is False
    assert settings.pii_enabled is True


def test_require_database_url_raises_when_missing() -> None:
    settings = Settings(_env_file=None)

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        settings.require_database_url(context="test")


def test_database_url_helpers() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql://user:pass@db.local:5432/listing_lens",
    )

    assert settings.require_database_url() == "postgresql://user:pass@db.local:5432/listing_lens"
    assert settings.sqlalchemy_database_url == "postgresql+psycopg://user:pass@db.local:5432/listing_lens"
    assert settings.database_host == "db.local"
