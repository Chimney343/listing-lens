from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool
from alembic import context
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str

    model_config = {
        "env_file": Path(__file__).parent.parent / ".env",
        "env_file_encoding": "utf-8-sig",  # handles BOM-encoded .env files
        "extra": "ignore",
    }


settings = Settings()

# SQLAlchemy requires the +psycopg driver token to select psycopg v3.
# Support plain postgresql:// and postgres:// URLs (e.g. from hosted providers)
# by rewriting them before handing the URL to SQLAlchemy.
_raw_url = settings.DATABASE_URL
if _raw_url.startswith(("postgresql://", "postgres://")):
    _raw_url = _raw_url.replace("://", "+psycopg://", 1)

config = context.config
config.set_main_option("sqlalchemy.url", _raw_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
