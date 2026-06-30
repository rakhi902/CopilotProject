"""The aggregate API router: the one place every feature router is mounted.

``app.main`` includes only this router, so adding a new feature area is a one-line
change here rather than an edit to the application factory.
"""

from fastapi import APIRouter

from app.api import analysis, auth, drafts, roles

api_router = APIRouter()

# Authentication: register / login / me.
api_router.include_router(auth.router)
# Roles: create (PDF + JD) and start generation, list, fetch, poll the latest draft.
api_router.include_router(roles.router)
# Drafts: fetch a single generated draft by id (used for polling + final display).
api_router.include_router(drafts.router)
# Extra analysis: ATS score, interview grading, salary coach, calendar export.
api_router.include_router(analysis.router)
