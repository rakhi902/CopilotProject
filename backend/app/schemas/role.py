"""Schemas for the ``Role`` resource (a targeted job application)."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import ApplicationStatus, DraftStatus


class RoleBase(BaseModel):
    """The user-supplied details of a target job."""

    job_title: str = Field(min_length=1, max_length=255)
    company: str = Field(min_length=1, max_length=255)
    jd_text: str = Field(min_length=1, description="The full job description text.")


class RoleCreate(RoleBase):
    """Request body for creating a role.

    The resume arrives separately as an uploaded PDF (multipart form data) handled
    by the endpoint, so it isn't part of this JSON body.
    """


class RoleRead(RoleBase):
    """Public representation of a role returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    # True once a resume PDF has been parsed and stored. Exposed as a boolean
    # (not the full text) to keep list responses small.
    has_source_resume: bool = False
    # The user-managed status, and the JD source URL when one was used.
    application_status: ApplicationStatus = ApplicationStatus.NOT_APPLIED
    jd_url: Optional[str] = None
    created_at: datetime


class RoleSubmissionResponse(BaseModel):
    """Returned by ``POST /roles``: the created role plus the draft to poll.

    The artifacts are generated in the background, so this hands back the new role
    along with the id and (PENDING) status of the draft the client should poll via
    ``GET /drafts/{draft_id}``.
    """

    role: RoleRead
    draft_id: int
    status: DraftStatus


class RoleStatusUpdate(BaseModel):
    """PATCH body to change a role's user-managed application status."""

    application_status: ApplicationStatus


class RoleBulkDeleteRequest(BaseModel):
    """Body for deleting several roles at once (multi-select in the UI)."""

    ids: List[int] = Field(min_length=1, description="Role ids to delete.")


class RoleBulkDeleteResponse(BaseModel):
    """Which of the requested roles were actually deleted (i.e. owned by the user)."""

    deleted_ids: List[int]
