"""Extra analysis endpoints, layered on top of an existing role.

Four small, standalone endpoints that do not touch the LangGraph generation
pipeline:

    POST /roles/{id}/ats-score          -> ATS keyword-density score + feedback
    POST /roles/{id}/interview/grade    -> grade a transcribed spoken answer
    POST /roles/{id}/salary-coach       -> two salary-negotiation scripts
    GET  /roles/{id}/export/calendar    -> a 1-week follow-up .ics download

The three LLM-backed endpoints call their service synchronously (the work is
short) and turn an LLM/config failure into a clean 5xx. They reuse the ownership
helpers from the roles router so access control stays identical.
"""

import logging
from typing import Callable, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

# Reuse the exact ownership + lookup helpers the roles router already uses.
from app.api.roles import _get_owned_role_or_404, _latest_draft_or_404, _safe_export_filename
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import User
from app.schemas import (
    ATSScore,
    InterviewGrade,
    InterviewGradeRequest,
    SalaryCoaching,
    SalaryCoachRequest,
)
from app.services.agents.llm_provider import LLMConfigurationError
from app.services.ats import score_ats
from app.services.calendar_export import build_followup_ics
from app.services.interview_grading import grade_answer
from app.services.salary import coach_salary

logger = logging.getLogger("job_copilot")

router = APIRouter(prefix="/roles", tags=["Analysis"])

_T = TypeVar("_T")


def _run_llm(operation: Callable[[], _T]) -> _T:
    """Run a synchronous LLM operation, turning failures into clean HTTP errors.

    Returns whatever ``operation`` returns. Raises 503 if the LLM provider isn't
    configured, and 502 on any other failure from the AI service.
    """
    try:
        return operation()
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 - surface a clean gateway error to the client
        logger.exception("LLM analysis call failed")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"AI service error: {exc}")


@router.post("/{role_id}/ats-score", response_model=ATSScore)
def ats_score(
    role_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ATSScore:
    """Score this role's rewritten resume against its JD for ATS keyword match.

    Raises 404 if the role/draft is missing, 409 if there's no rewritten resume to
    score yet, and 502/503 on an AI failure.
    """
    role = _get_owned_role_or_404(db, role_id, current_user.id)
    draft = _latest_draft_or_404(db, role.id)
    if not (draft.resume_rewrite or {}).get("bullets"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No rewritten resume to score yet.")
    return _run_llm(lambda: score_ats(draft.resume_rewrite, role.jd_text))


@router.post("/{role_id}/interview/grade", response_model=InterviewGrade)
def interview_grade(
    role_id: int,
    payload: InterviewGradeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InterviewGrade:
    """Grade a candidate's transcribed spoken answer to one interview question.

    Raises 404 if the role is missing or not owned, and 502/503 on an AI failure.
    """
    _get_owned_role_or_404(db, role_id, current_user.id)
    return _run_llm(lambda: grade_answer(payload.question, payload.sample_answer, payload.user_answer))


@router.post("/{role_id}/salary-coach", response_model=SalaryCoaching)
def salary_coach(
    role_id: int,
    payload: SalaryCoachRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SalaryCoaching:
    """Generate two negotiation scripts for this role's offer.

    Raises 404 if the role is missing or not owned, and 502/503 on an AI failure.
    """
    role = _get_owned_role_or_404(db, role_id, current_user.id)
    return _run_llm(lambda: coach_salary(role.job_title, role.company, payload.offered_salary))


@router.get("/{role_id}/export/calendar")
def export_followup_calendar(
    role_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Download a 1-week follow-up reminder as an iCalendar (.ics) file.

    Raises 404 if the role is missing or not owned by the user.
    """
    role = _get_owned_role_or_404(db, role_id, current_user.id)
    ics_text = build_followup_ics(role.company, role.job_title)
    filename = _safe_export_filename(f"Follow up - {role.company}", "ics")
    return Response(
        content=ics_text,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
