"""Application configuration, loaded once from the environment.

Everything tunable lives here on a single validated ``Settings`` object: the
secrets, the database URL, the allowed CORS origins, and the LLM provider
settings. Keeping it in one place means no other module has to read
``os.environ`` directly, the values are type-checked once at startup, and tests
can build a ``Settings`` with explicit overrides instead of patching environment
variables.

Values come from ``backend/.env`` (see ``.env.example``) and fall back to the
defaults below when a variable isn't set.
"""

from functools import lru_cache
from typing import List, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(raw_url: str) -> str:
    """Return a database URL that SQLAlchemy 2.0 and our drivers accept as-is.

    Render (like Heroku) hands out managed PostgreSQL using the old
    ``postgres://`` scheme, but SQLAlchemy 2.0 only understands ``postgresql://``.
    We rewrite just that prefix so the URL Render gives us works unchanged. Any
    other URL, including the local SQLite default, is returned untouched.
    """
    if raw_url.startswith("postgres://"):
        return raw_url.replace("postgres://", "postgresql://", 1)
    return raw_url


class Settings(BaseSettings):
    """All runtime configuration for the backend, validated by Pydantic.

    Field names map onto environment variable names (case-insensitively), so the
    ``jwt_secret_key`` field is filled from the ``JWT_SECRET_KEY`` variable.
    """

    # Tell pydantic-settings where and how to read the configuration.
    model_config = SettingsConfigDict(
        env_file=".env",             # resolved relative to the process CWD (backend/)
        env_file_encoding="utf-8",
        case_sensitive=False,        # JWT_SECRET_KEY and jwt_secret_key are the same key
        extra="ignore",              # ignore unrelated env vars rather than erroring
    )

    # Application metadata
    app_name: str = "Job Application Co-Pilot"
    environment: str = "development"       # "development" or "production"
    debug: bool = True

    # Security / JSON Web Tokens.
    # The default secret below is only a placeholder; a real deployment must pass
    # its own value through the environment.
    jwt_secret_key: str = "change-me-to-a-long-random-secret-string"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # Database. Local development falls back to a SQLite file; production sets
    # DATABASE_URL to a PostgreSQL URL (Render provisions one and injects it). The
    # _normalize_database_url validator below rewrites Render's legacy "postgres://"
    # scheme to "postgresql://" so SQLAlchemy 2.0 accepts it.
    database_url: str = "sqlite:///./job_copilot.db"

    # CORS. Stored as one comma-separated string (which round-trips cleanly
    # through a .env file) and exposed as a parsed list via cors_origins below.
    backend_cors_origins: str = "http://localhost:5500,http://127.0.0.1:5500"

    # LLM provider selection
    llm_provider: str = "groq"             # "groq" or "openai"
    groq_api_key: Optional[str] = None
    groq_model: str = "llama-3.3-70b-versatile"
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.3
    llm_request_timeout_seconds: int = 60

    @property
    def cors_origins(self) -> List[str]:
        """The configured CORS origins as a clean list, blanks dropped."""
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        """Rewrite Render's legacy ``postgres://`` scheme to ``postgresql://``.

        Doing it here means the app engine (``core.database``) and Alembic
        (``migrations/env.py``) both read one already-normalized URL and can't
        drift apart. ``DATABASE_URL`` feeds this field automatically, and the
        SQLite default above is used whenever it isn't set.
        """
        return normalize_database_url(value)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide ``Settings`` singleton.

    The ``lru_cache`` makes sure the ``.env`` file is parsed exactly once; every
    caller (the database engine, the security layer, the FastAPI dependencies)
    then shares the same configuration object.
    """
    return Settings()
