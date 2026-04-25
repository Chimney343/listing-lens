from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context
from config.settings import settings


_raw_url = settings.sqlalchemy_database_url

config = context.config
config.set_main_option("sqlalchemy.url", _raw_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _confirm_production_migration() -> None:
    if settings.env != "production":
        return

    print(f"[alembic] ENV=production DATABASE_HOST={settings.database_host}")
    try:
        answer = input("Apply migration to production database? [y/N]: ").strip().lower()
    except EOFError as error:
        raise RuntimeError("Migration aborted: no confirmation input available") from error

    if answer not in {"y", "yes"}:
        raise RuntimeError("Migration aborted by user")


def run_migrations_offline() -> None:
    _confirm_production_migration()
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
    _confirm_production_migration()
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
