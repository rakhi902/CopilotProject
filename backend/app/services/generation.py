"""Background draft generation: run the pipeline and save the result.

This is the bridge between the HTTP layer and the LangGraph pipeline. It's a plain
function that opens its own database session, because it runs after the HTTP
response has been sent (via FastAPI ``BackgroundTasks``), by which point the
request's own session is already closed.
"""

import logging
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.enums import DraftStatus
from app.models import Draft, Role
from app.services.agents.graph import run_pipeline, run_single_agent

logger = logging.getLogger("job_copilot")


def generate_draft_in_background(
    draft_id: int,
    session_factory: Optional[Callable[[], Session]] = None,
) -> None:
    """Generate every artifact for a draft and save them to the database.

    Meant to be scheduled via ``BackgroundTasks.add_task``. Any failure is recorded
    on the draft row (``status=FAILED`` + ``error_message``) rather than raised,
    because there's no HTTP response left to attach an error to. The draft's status
    moves PENDING -> PROCESSING -> COMPLETED/FAILED as it runs.

    ``session_factory`` is an optional callable returning a new DB session; it
    defaults to the application's ``SessionLocal`` (the production path) and is
    overridable for tests.
    """
    # Resolve the factory at call time (not as a default argument) so tests can
    # rebind SessionLocal on this module and have it take effect here.
    factory = session_factory or SessionLocal
    db = factory()
    try:
        draft = db.get(Draft, draft_id)
        if draft is None:
            logger.warning("Draft %s vanished before generation could start", draft_id)
            return

        role = db.get(Role, draft.role_id)
        if role is None:
            draft.status = DraftStatus.FAILED.value
            draft.error_message = "The role for this draft no longer exists."
            db.commit()
            return

        # Mark in-progress so a polling frontend can show a spinner.
        draft.status = DraftStatus.PROCESSING.value
        db.commit()

        try:
            result = run_pipeline(
                resume_text=role.source_resume_text or "",
                jd_text=role.jd_text,
                job_title=role.job_title,
                company=role.company,
            )
            # Save whatever each agent produced (some may be None if an agent
            # failed but the pipeline as a whole carried on).
            draft.fit_analysis = result.get("fit_analysis")
            draft.resume_rewrite = result.get("resume_rewrite")
            draft.cover_letter = result.get("cover_letter")
            draft.interview_qa = result.get("interview_qa")

            agent_errors = result.get("errors") or []
            if agent_errors:
                draft.status = DraftStatus.FAILED.value
                draft.error_message = " | ".join(agent_errors)
            else:
                draft.status = DraftStatus.COMPLETED.value
                draft.error_message = None
        except Exception as pipeline_error:  # noqa: BLE001 - record any failure on the row
            logger.exception("Pipeline crashed for draft %s", draft_id)
            draft.status = DraftStatus.FAILED.value
            draft.error_message = f"Generation failed: {pipeline_error}"

        db.commit()
    finally:
        db.close()


def regenerate_artifact_in_background(
    draft_id: int,
    artifact: str,
    session_factory: Optional[Callable[[], Session]] = None,
) -> None:
    """Re-run a single agent and save just that one artifact onto the draft.

    This powers the per-artifact "Regenerate" buttons: instead of re-running the
    whole pipeline, it re-runs only the agent behind ``artifact`` (grounded in the
    draft's existing fit analysis) and overwrites that one column. The draft's
    other artifacts are left alone.

    Status moves PROCESSING -> COMPLETED (artifact refreshed) or FAILED (the agent
    errored; the previous value is kept, not nulled). ``session_factory`` is
    overridable for tests.
    """
    factory = session_factory or SessionLocal
    db = factory()
    try:
        draft = db.get(Draft, draft_id)
        if draft is None:
            logger.warning("Draft %s vanished before regeneration could start", draft_id)
            return

        role = db.get(Role, draft.role_id)
        if role is None:
            draft.status = DraftStatus.FAILED.value
            draft.error_message = "The role for this draft no longer exists."
            db.commit()
            return

        # Mark in-progress so the polling frontend can show the artifact refreshing.
        draft.status = DraftStatus.PROCESSING.value
        db.commit()

        try:
            outcome = run_single_agent(
                artifact,
                resume_text=role.source_resume_text or "",
                jd_text=role.jd_text,
                job_title=role.job_title,
                company=role.company,
                fit_analysis=draft.fit_analysis,
            )
            if outcome["errors"]:
                # Keep the prior artifact value; surface the failure on the row.
                draft.status = DraftStatus.FAILED.value
                draft.error_message = " | ".join(outcome["errors"])
            else:
                setattr(draft, outcome["state_key"], outcome["value"])
                draft.status = DraftStatus.COMPLETED.value
                draft.error_message = None
        except Exception as regen_error:  # noqa: BLE001 - record any failure on the row
            logger.exception("Regeneration of %s crashed for draft %s", artifact, draft_id)
            draft.status = DraftStatus.FAILED.value
            draft.error_message = f"Regeneration failed: {regen_error}"

        db.commit()
    finally:
        db.close()
