"""FastAPI application factory for the Job Application Co-Pilot.

Builds the runnable ASGI app: creates FastAPI, sets up CORS so the vanilla JS
frontend (served from a different origin) can call the API, registers the feature
routers, and exposes a health-check endpoint.

Run it from the ``backend`` directory with the venv active::

    uvicorn app.main:app --reload

Alembic owns the database schema (run ``alembic upgrade head`` once), so the
factory deliberately doesn't create any tables itself.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings

logger = logging.getLogger("job_copilot")

# Resolve configuration once, at import time, and share it across the factory.
settings = get_settings()


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Run startup and shutdown logic around the app's serving lifetime.

    On startup we log the active configuration, which is useful when checking
    which LLM provider or database is actually in play. Schema management is left
    to Alembic, so nothing schema-related happens here.
    """
    logger.info(
        "Starting %s (environment=%s, llm_provider=%s)",
        settings.app_name,
        settings.environment,
        settings.llm_provider,
    )
    yield
    logger.info("Shutting down %s", settings.app_name)


def create_application() -> FastAPI:
    """Build, configure, and return the FastAPI application."""
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Turn a resume + job description into a tailored application kit.",
        lifespan=lifespan,
    )

    # The browser frontend runs on a different origin (a Live Server port, say),
    # so the browser blocks its fetch() calls unless we explicitly allow them.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount every feature router through the single aggregate router.
    application.include_router(api_router)

    @application.get("/health", tags=["Health"], summary="Liveness probe")
    def health_check() -> dict:
        """Return a tiny payload so uptime checks can confirm the API is alive."""
        return {"status": "ok", "app": settings.app_name}

    return application


# The module-level ASGI app uvicorn looks for: "uvicorn app.main:app".
app = create_application()
