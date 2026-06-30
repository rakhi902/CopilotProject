"""Alembic migration environment for the Job Application Co-Pilot.

This script is run by the ``alembic`` command. It connects Alembic to the
application's own SQLAlchemy metadata and database URL so that:

    * ``alembic revision --autogenerate`` can diff the ORM models against the live
      database and emit the difference as a migration, and
    * ``alembic upgrade`` / ``downgrade`` can apply or revert those migrations.
"""

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make the application package importable. This file lives at
# backend/migrations/env.py, so the backend directory is two levels up. Putting it
# on sys.path lets "import app..." work no matter which directory alembic was
# launched from.
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# Import these after the sys.path tweak. Importing app.models registers every
# table on Base.metadata, which is what autogenerate compares against.
from app.core.config import get_settings, normalize_database_url  # noqa: E402  (import after sys.path setup)
from app.models import Base                # noqa: E402

# The Alembic Config object gives access to the values in alembic.ini.
config = context.config

# Point Alembic at the same database the app uses by injecting the real URL from
# our settings. normalize_database_url rewrites Render's legacy "postgres://"
# scheme to "postgresql://" for SQLAlchemy 2.0. It's idempotent: the Settings
# layer already applies it, and doing it here keeps env.py correct on its own even
# if it's run in isolation.
config.set_main_option("sqlalchemy.url", normalize_database_url(get_settings().database_url))

# Configure Python logging from the alembic.ini logging sections, if present.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The metadata Alembic introspects when autogenerating migrations.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode: emit SQL text without a live DB.

    Configures the context with just a URL and renders the migration statements as
    literal SQL. Handy for producing a script to run by hand against a database.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # render_as_batch lets SQLite emulate ALTER TABLE (its native support is
        # limited), which keeps future migrations portable.
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode, against a live database connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,   # see the note in run_migrations_offline
            compare_type=True,      # detect column type changes during autogenerate
        )
        with context.begin_transaction():
            context.run_migrations()


# Alembic picks offline vs. online based on how it was invoked (the --sql flag).
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
