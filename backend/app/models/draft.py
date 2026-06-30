"""The ``Draft`` model: the generated application kit for a role.

A draft holds the four artifacts the LangGraph pipeline produces, plus a
``status`` field that tracks the pipeline's progress (generation runs in the
background and the frontend polls for completion). The structured artifacts are
stored as JSON so their rich shape (lists of bullet rewrites, Q&A pairs) survives
without extra tables; the exact shapes are defined by the Pydantic schemas in
``app.schemas.draft``.
"""

from typing import Any, Dict, Optional, TYPE_CHECKING

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin
from app.core.enums import DraftStatus

if TYPE_CHECKING:
    from app.models.role import Role


class Draft(TimestampMixin, Base):
    """The saved outputs of one pipeline run for a single role."""

    __tablename__ = "drafts"

    id: Mapped[int] = mapped_column(primary_key=True)

    # The role whose inputs produced this draft. Cascade-deleted with the role.
    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # Pipeline progress, stored as the string value of the DraftStatus enum;
    # starts at PENDING.
    status: Mapped[str] = mapped_column(
        String(20),
        default=DraftStatus.PENDING.value,
        nullable=False,
    )
    # Set only when status == FAILED: the reason generation failed, shown to the
    # user instead of a silent empty result.
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # The generated artifacts, one column per agent.
    # Fit Analyst: requirements met / missing + what to emphasize.
    fit_analysis: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    # Resume Writer: original -> rewritten bullet pairs (feeds the Diff View).
    resume_rewrite: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    # Cover Letter: the one-page letter, stored as plain / markdown text.
    cover_letter: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Interviewer: likely questions with resume-grounded sample answers.
    interview_qa: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    role: Mapped["Role"] = relationship(back_populates="drafts")

    def __repr__(self) -> str:
        return f"<Draft id={self.id} role_id={self.role_id} status={self.status!r}>"
