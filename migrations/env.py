"""
Alembic environment script.

Runs in two modes:
  - offline: generates SQL scripts without a live DB connection
  - online:  connects to the database and applies migrations directly

DATABASE_URL is sourced from the application's Settings object (which reads
from .env) so credentials are never hardcoded here or in alembic.ini.
"""
from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# ------------------------------------------------------------------ #
# Ensure the project root is on sys.path so backend.app.* is importable
# when alembic is run from the project root.
# ------------------------------------------------------------------ #
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ------------------------------------------------------------------ #
# Import application models to populate Base.metadata.
# Import order: Base first, then the model registry.
# ------------------------------------------------------------------ #
from backend.app.db.base import Base  # noqa: E402
import backend.app.models  # noqa: E402  — registers all models against Base

# ------------------------------------------------------------------ #
# Pull DATABASE_URL from application settings (reads .env)
# ------------------------------------------------------------------ #
from backend.app.core.config import get_settings  # noqa: E402

settings = get_settings()

# ------------------------------------------------------------------ #
# Alembic Config object — gives access to alembic.ini values
# ------------------------------------------------------------------ #
config = context.config

# Override the sqlalchemy.url with the value from our Settings
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Set up Python logging as configured in alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The metadata object that autogenerate inspects
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    Generates SQL statements rather than connecting to the database.
    Useful for reviewing changes or applying them in environments where
    a direct DB connection is not available during CI.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.

    Connects to the database and applies pending migrations in a single
    transaction. Rolls back automatically on failure.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
