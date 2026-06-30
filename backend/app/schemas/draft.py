"""Schemas for the ``Draft`` resource and its four generated artifacts.

These do double duty: they're the response contracts the API returns to the
frontend, and they're the exact JSON shapes the LangGraph agents must produce and
the ``Draft`` model stores in its JSON columns. Defining them gives the agents a
precise, typed target.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import DraftStatus


# Fit Analyst (agent 1)
class FitAnalysis(BaseModel):
    """How well the resume matches the JD, as judged by the Fit Analyst."""

    met_requirements: List[str] = Field(
        default_factory=list,
        description="JD requirements the resume already clearly satisfies.",
    )
    missing_requirements: List[str] = Field(
        default_factory=list,
        description="JD requirements that are absent or weak in the resume.",
    )
    points_to_emphasize: List[str] = Field(
        default_factory=list,
        description="Existing strengths worth foregrounding for this specific JD.",
    )
    overall_summary: str = Field(
        default="",
        description="A short narrative judgement of the candidate's overall fit.",
    )
    fit_score: Optional[int] = Field(
        default=None,
        ge=0,
        le=100,
        description=(
            "Integer 0-100 fit score, computed by rubric: start at 100, -15 per missing "
            "mandatory requirement, -5 per missing preferred requirement, clamped to 0-100."
        ),
    )


# Resume Writer (agent 2)
class ResumeBulletRewrite(BaseModel):
    """A single original -> rewritten bullet pair (one row of the Diff View)."""

    section: Optional[str] = Field(
        default=None,
        description="Where the bullet lives, e.g. 'Experience - Acme Corp'.",
    )
    original_bullet: str = Field(description="The bullet exactly as the resume had it.")
    rewritten_bullet: str = Field(description="The improved, JD-aligned rewrite.")
    rationale: str = Field(
        default="",
        description="Why the rewrite is stronger / which JD keywords it weaves in.",
    )


class ResumeRewrite(BaseModel):
    """The full set of bullet rewrites produced by the Resume Writer."""

    bullets: List[ResumeBulletRewrite] = Field(default_factory=list)
    summary_of_changes: Optional[str] = Field(
        default=None,
        description="A high-level note on the rewriting strategy that was applied.",
    )


# Interviewer (agent 4)
class InterviewQuestion(BaseModel):
    """A likely interview question paired with a resume-grounded sample answer."""

    question: str
    sample_answer: str
    grounded_in: Optional[str] = Field(
        default=None,
        description="The specific resume experience the sample answer draws on.",
    )


class InterviewPrep(BaseModel):
    """The set of likely interview questions from the Interviewer."""

    questions: List[InterviewQuestion] = Field(default_factory=list)


# Cover-letter fact-check (the "Governor" self-correction step)
class CoverLetterVerification(BaseModel):
    """The verifier's verdict on whether a cover letter invented any qualifications.

    Produced by the ``verify_cover_letter`` node, which checks a drafted letter
    against the resume (the only source of truth). This is an internal
    pipeline-control object: it drives the self-correction loop and is never saved
    to the database or returned to the frontend.
    """

    has_unsupported_claims: bool = Field(
        description="True if the letter claims any skill or experience not proven in the resume.",
    )
    unsupported_claims: List[str] = Field(
        default_factory=list,
        description="The exact unsupported phrases to remove on rewrite (empty when grounded).",
    )


# The Draft resource itself
class DraftStatusRead(BaseModel):
    """Lightweight status payload the frontend polls while generation runs."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    role_id: int
    status: DraftStatus
    error_message: Optional[str] = None


class ArtifactRegenerationResponse(BaseModel):
    """Returned by the per-artifact regenerate endpoint: the draft to re-poll.

    Regeneration re-runs a single agent in the background, so (like the initial
    submission) it returns right away with the draft id and its status; the client
    polls the draft until the one artifact is refreshed.
    """

    draft_id: int
    artifact: str
    status: DraftStatus


class DraftRead(BaseModel):
    """The complete generated kit for a role, returned once generation is done.

    Reads straight from the ``Draft`` object. The JSON columns (``fit_analysis``,
    ``resume_rewrite``, ``interview_qa``) are validated into their nested schemas
    automatically by Pydantic.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    role_id: int
    status: DraftStatus
    error_message: Optional[str] = None

    fit_analysis: Optional[FitAnalysis] = None
    resume_rewrite: Optional[ResumeRewrite] = None
    cover_letter: Optional[str] = None
    interview_qa: Optional[InterviewPrep] = None

    created_at: datetime
    updated_at: datetime
