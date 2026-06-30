"""Core infrastructure shared across the whole application.

The cross-cutting concerns that aren't tied to any one feature:

    config     typed, environment-driven application settings
    security   password hashing and JWT creation / verification
    database   SQLAlchemy engine, session factory, and declarative Base
    deps       reusable FastAPI dependencies (current user, DB session)

These modules stay feature-agnostic so any layer can import them without creating
circular dependencies.
"""
