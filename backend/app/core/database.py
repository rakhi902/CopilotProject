"""SQLAlchemy wiring: the engine, the session factory, and the declarative Base.

This module owns the connection concerns so the rest of the app doesn't have to
care how persistence is set up:

    * ``engine``         the connection pool to the configured database
    * ``SessionLocal``   a factory that hands out short-lived DB sessions
    * ``Base``           the declarative base every ORM model inherits from
    * ``TimestampMixin`` reusable created_at / updated_at columns
    * ``get_db``         a FastAPI dependency that yields one session per request

The models in ``app.models`` import ``Base`` (and ``TimestampMixin``) from here,
so there's a single source of truth for the metadata Alembic migrates.
"""

from datetime import datetime
from typing import Generator

from sqlalchemy import DateTime, create_engine, event, func
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)

from app.core.config import get_settings

# Load configuration once. settings.database_url is already engine-ready: it
# comes from DATABASE_URL when set (for example Render's managed PostgreSQL,
# whose legacy "postgres://" prefix the Settings layer rewrites to
# "postgresql://") and otherwise falls back to the local SQLite file.
settings = get_settings()

# check_same_thread is a SQLite-only flag (it lets one SQLite connection be
# shared across FastAPI's worker threads). PostgreSQL's driver rejects it, so we
# only pass connect_args when we're actually on SQLite.
is_sqlite = settings.database_url.startswith("sqlite")
engine_connect_args = {"check_same_thread": False} if is_sqlite else {}

# The engine is the long-lived gateway to the database (a pool of connections),
# created once at import time. The same code drives SQLite (local dev) and
# PostgreSQL (production); only the URL and the SQLite-only connect_args differ.
engine = create_engine(
    settings.database_url,
    connect_args=engine_connect_args,
    echo=False,        # set True to log every SQL statement while debugging
    future=True,
)


# SQLite doesn't enforce foreign keys unless you ask it to, and the setting is
# per-connection. We turn it on for every new connection so our ON DELETE CASCADE
# rules (User -> Role -> Draft) actually fire.
if is_sqlite:

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
        """Turn on foreign-key enforcement for each new SQLite connection."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


# SessionLocal is a configured factory: calling it returns a fresh Session bound
# to our engine. We turn off autoflush/autocommit for explicit, predictable
# transactions, and keep attributes readable after commit so endpoints can safely
# return ORM objects they've just saved.
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


class Base(DeclarativeBase):
    """The declarative base every ORM model inherits from.

    Because all models share this one ``Base``, every table registers on a single
    ``Base.metadata`` object, which is what Alembic reads to autogenerate
    migrations.
    """


class TimestampMixin:
    """Reusable audit columns for models that track when a row changed.

    ``created_at`` is set by the database when the row is first inserted;
    ``updated_at`` is set on insert and refreshed by the database on every update.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


def get_db() -> Generator[Session, None, None]:
    """Yield a database session for the life of a single request.

    Meant to be used as a FastAPI dependency (``db: Session = Depends(get_db)``).
    The session is always closed afterward, even if the endpoint raises, so
    connections never leak back into the pool in a dirty state.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
