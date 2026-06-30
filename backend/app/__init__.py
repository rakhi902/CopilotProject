"""Top-level package for the Job Application Co-Pilot backend.

Everything server-side lives here, split into focused sub-packages so each layer
is easy to find and reason about:

    api/       HTTP routers (the FastAPI endpoints the frontend calls)
    core/      cross-cutting concerns: configuration, security, dependencies
    models/    SQLAlchemy ORM models (the database schema as Python classes)
    schemas/   Pydantic models (request/response validation contracts)
    services/  business logic: PDF parsing and the LangGraph agent pipeline
    main.py    the FastAPI application factory and app wiring

The split follows the request lifecycle: a request enters through ``api``, is
validated by ``schemas``, authorized via ``core``, fulfilled by ``services``, and
persisted through ``models``.
"""
