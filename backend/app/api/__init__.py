"""HTTP API layer: the FastAPI routers that expose the backend to the frontend.

Each module here defines an ``APIRouter`` for one resource group (authentication,
roles, drafts, analysis). The routers stay thin: they validate input with
``schemas``, hand the real work to ``services``, and translate the results (or
failures) into HTTP responses with the right status codes.
"""
