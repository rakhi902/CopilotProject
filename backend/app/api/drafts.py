"""Drafts API: fetch a single generated draft (for polling and final display)."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import Draft, Role, User
from app.schemas import DraftRead

router = APIRouter(prefix="/drafts", tags=["Drafts"])


@router.get("/{draft_id}", response_model=DraftRead)
def get_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Draft:
    """Fetch a single draft by id, scoped to the authenticated owner.

    Returns the ``DraftRead`` (its artifacts are ``null`` until generation
    finishes). Raises 404 if the draft doesn't exist, or its role isn't owned by
    the requesting user (hidden behind a 404 rather than a 403).
    """
    draft = db.get(Draft, draft_id)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found.")

    role = db.get(Role, draft.role_id)
    if role is None or role.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found.")

    return draft
