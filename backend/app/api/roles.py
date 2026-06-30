"""Roles API: create a job application (PDF + JD), then list / fetch results.

``POST /roles`` is the entry point to the whole product: it parses the uploaded
resume, stores the role, creates a PENDING draft, and kicks off the LangGraph
pipeline in the background. The other endpoints let the frontend list a user's
roles and poll for the generated draft.
"""

import logging
import re
from typing import List, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.enums import DraftStatus
from app.models import Draft, Role, User
from app.schemas import (
    ArtifactRegenerationResponse,
    DraftRead,
    RoleBulkDeleteRequest,
    RoleBulkDeleteResponse,
    RoleRead,
    RoleStatusUpdate,
    RoleSubmissionResponse,
)
from app.services.agents.graph import REGENERATABLE_ARTIFACTS
from app.services.export import build_cover_letter_docx, build_resume_pdf
from app.services.generation import (
    generate_draft_in_background,
    regenerate_artifact_in_background,
)
from app.services.jd_scraping import JDScrapingError, scrape_jd_text
from app.services.pdf_parsing import ResumeParsingError, extract_text_from_pdf_bytes

logger = logging.getLogger("job_copilot")

router = APIRouter(prefix="/roles", tags=["Roles"])

# Reject absurdly large uploads early; a text resume is far below this.
_MAX_PDF_BYTES = 5 * 1024 * 1024  # 5 MB


def _get_owned_role_or_404(db: Session, role_id: int, user_id: int) -> Role:
    """Fetch a role by id, making sure it belongs to the requesting user.

    Raises 404 if the role doesn't exist or belongs to someone else. We use 404
    rather than 403 so we never reveal another user's ids.
    """
    role = db.get(Role, role_id)
    if role is None or role.owner_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found.")
    return role


def _latest_draft_or_404(db: Session, role_id: int) -> Draft:
    """Return the most recent draft for a role, or raise 404 if there isn't one."""
    draft = db.execute(
        select(Draft).where(Draft.role_id == role_id).order_by(Draft.created_at.desc())
    ).scalars().first()
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No draft exists for this role yet.")
    return draft


def _safe_export_filename(stem: str, extension: str) -> str:
    """Build a filesystem-safe download filename like ``Cover Letter - Acme.docx``."""
    cleaned = re.sub(r"[^A-Za-z0-9 _.-]+", "", stem).strip() or "download"
    return f"{cleaned}.{extension}"


@router.post("", response_model=RoleSubmissionResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_role_and_start_generation(
    background_tasks: BackgroundTasks,
    job_title: str = Form(..., min_length=1, max_length=255),
    company: str = Form(..., min_length=1, max_length=255),
    jd_text: Optional[str] = Form(None, description="Pasted job description text."),
    jd_url: Optional[str] = Form(None, description="A JD URL to scrape (used when jd_text is empty)."),
    resume_pdf: UploadFile = File(..., description="The candidate's resume as a PDF."),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RoleSubmissionResponse:
    """Create a role from a resume PDF + JD and start generating its draft.

    The heavy LLM work runs in the background; this returns right away (202) with
    the new role and the id of the PENDING draft the client should poll. Raises 413
    if the file is too large and 422 if the PDF can't be parsed into text.
    """
    # Guard against oversized uploads, checking the declared size first if present.
    if resume_pdf.size is not None and resume_pdf.size > _MAX_PDF_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="The PDF is too large (limit is 5 MB).",
        )

    pdf_bytes = await resume_pdf.read()
    if len(pdf_bytes) > _MAX_PDF_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="The PDF is too large (limit is 5 MB).",
        )

    # Turn the PDF into plain text up front so a bad file is rejected now (with a
    # clear 422) rather than failing silently later in the background task.
    try:
        parsed_resume_text = extract_text_from_pdf_bytes(pdf_bytes)
    except ResumeParsingError as parse_error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(parse_error))

    # Resolve the job description: prefer pasted text, otherwise scrape the URL.
    resolved_jd_text = (jd_text or "").strip()
    cleaned_jd_url = (jd_url or "").strip() or None
    if not resolved_jd_text and cleaned_jd_url:
        try:
            resolved_jd_text = scrape_jd_text(cleaned_jd_url)
        except JDScrapingError as scrape_error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(scrape_error))
    if not resolved_jd_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide the job description as text (jd_text) or a link (jd_url).",
        )

    # Save the role (the pipeline's inputs).
    role = Role(
        job_title=job_title,
        company=company,
        jd_text=resolved_jd_text,
        jd_url=cleaned_jd_url,
        source_resume_text=parsed_resume_text,
        owner_id=current_user.id,
    )
    db.add(role)
    db.commit()
    db.refresh(role)

    # Save a PENDING draft to hold the eventual outputs.
    draft = Draft(role_id=role.id, status=DraftStatus.PENDING.value)
    db.add(draft)
    db.commit()
    db.refresh(draft)

    # Hand the slow LLM work to a background task and respond immediately.
    background_tasks.add_task(generate_draft_in_background, draft.id)

    return RoleSubmissionResponse(
        role=RoleRead.model_validate(role),
        draft_id=draft.id,
        status=DraftStatus.PENDING,
    )


@router.get("", response_model=List[RoleRead])
def list_roles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[Role]:
    """List the authenticated user's roles, newest first."""
    rows = db.execute(
        select(Role).where(Role.owner_id == current_user.id).order_by(Role.created_at.desc())
    ).scalars().all()
    return list(rows)


@router.get("/{role_id}", response_model=RoleRead)
def get_role(
    role_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Role:
    """Fetch a single role owned by the authenticated user (404 otherwise)."""
    return _get_owned_role_or_404(db, role_id, current_user.id)


@router.get("/{role_id}/draft", response_model=DraftRead)
def get_latest_draft_for_role(
    role_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Draft:
    """Fetch the most recent draft for one of the user's roles (used for polling).

    Raises 404 if the role isn't found or owned, or has no draft yet.
    """
    role = _get_owned_role_or_404(db, role_id, current_user.id)
    return _latest_draft_or_404(db, role.id)


@router.patch("/{role_id}", response_model=RoleRead)
def update_role_application_status(
    role_id: int,
    payload: RoleStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Role:
    """Update a role's user-managed application status.

    Raises 404 if the role isn't found or owned, and 422 on an invalid status.
    """
    role = _get_owned_role_or_404(db, role_id, current_user.id)
    role.application_status = payload.application_status.value
    db.commit()
    db.refresh(role)
    return role


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(
    role_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Delete one of the user's roles; its drafts cascade away with it.

    Returns an empty 204. Raises 404 if the role isn't found or owned by the user.
    """
    role = _get_owned_role_or_404(db, role_id, current_user.id)
    db.delete(role)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/bulk-delete", response_model=RoleBulkDeleteResponse)
def bulk_delete_roles(
    payload: RoleBulkDeleteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RoleBulkDeleteResponse:
    """Delete several of the user's roles at once (multi-select in the UI).

    Quietly ignores ids that don't exist or aren't owned by the caller, and reports
    exactly which ids were actually deleted.
    """
    rows = db.execute(
        select(Role).where(Role.owner_id == current_user.id, Role.id.in_(payload.ids))
    ).scalars().all()
    deleted_ids = [role.id for role in rows]
    for role in rows:
        db.delete(role)
    db.commit()
    return RoleBulkDeleteResponse(deleted_ids=deleted_ids)


@router.post(
    "/{role_id}/regenerate/{artifact}",
    response_model=ArtifactRegenerationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def regenerate_artifact(
    role_id: int,
    artifact: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ArtifactRegenerationResponse:
    """Re-run one agent for this role's latest draft, without the full pipeline.

    ``artifact`` is one of "resume", "cover", or "interview". Returns the draft id
    to poll. Raises 422 for an unknown artifact and 404 if the role/draft is
    missing or not owned by the user.
    """
    if artifact not in REGENERATABLE_ARTIFACTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Cannot regenerate '{artifact}'. Choose one of: {', '.join(REGENERATABLE_ARTIFACTS)}.",
        )
    role = _get_owned_role_or_404(db, role_id, current_user.id)
    draft = _latest_draft_or_404(db, role.id)
    background_tasks.add_task(regenerate_artifact_in_background, draft.id, artifact)
    return ArtifactRegenerationResponse(draft_id=draft.id, artifact=artifact, status=DraftStatus.PROCESSING)


@router.get("/{role_id}/export/cover-letter.docx")
def export_cover_letter_docx(
    role_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Download this role's cover letter as a Word ``.docx`` file.

    Raises 404 if the role/draft is missing, and 409 if no cover letter has been
    generated yet.
    """
    role = _get_owned_role_or_404(db, role_id, current_user.id)
    draft = _latest_draft_or_404(db, role.id)
    if not draft.cover_letter:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No cover letter has been generated yet.")
    data = build_cover_letter_docx(draft.cover_letter, job_title=role.job_title, company=role.company)
    filename = _safe_export_filename(f"Cover Letter - {role.company}", "docx")
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{role_id}/export/resume.pdf")
def export_resume_pdf(
    role_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Download this role's rewritten resume as a ``.pdf`` file.

    Raises 404 if the role/draft is missing, and 409 if no resume rewrite has been
    generated yet.
    """
    role = _get_owned_role_or_404(db, role_id, current_user.id)
    draft = _latest_draft_or_404(db, role.id)
    rewrite = draft.resume_rewrite or {}
    if not rewrite.get("bullets"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No resume rewrite has been generated yet.")
    data = build_resume_pdf(rewrite, job_title=role.job_title, company=role.company)
    filename = _safe_export_filename(f"Resume - {role.company}", "pdf")
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
