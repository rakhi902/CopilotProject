"""The ``Role`` model: one targeted job application.

A role holds the inputs to the pipeline (the target job's title, company, and
full JD text, plus the plain text extracted from the uploaded resume PDF) and
owns the ``Draft`` rows that hold the generated outputs.
"""

from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin
from app.core.enums import ApplicationStatus

if TYPE_CHECKING:
    from app.models.draft import Draft
    from app.models.user import User


class Role(TimestampMixin, Base):
    """A single job a user is preparing to apply for."""

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)

    # The target job, as the user gave it.
    job_title: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    # The full job description. Text rather than String because it's long-form.
    jd_text: Mapped[str] = mapped_column(Text, nullable=False)
    # The URL the JD was scraped from, when the user gave a link instead of
    # pasting text. Kept for reference and re-scraping. Nullable.
    jd_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # The status the user curates by hand in the UI (Not Applied / Applied /
    # Interviewing / Rejected). Separate from a Draft's generation status.
    # Defaults to Not Applied when the role is created.
    application_status: Mapped[str] = mapped_column(
        String(20),
        default=ApplicationStatus.NOT_APPLIED.value,
        nullable=False,
    )

    # The candidate's source material: the plain text extracted from the uploaded
    # PDF. Stored on the role so the pipeline can be re-run and the frontend's
    # Diff View can show the original bullets next to the rewritten ones. Nullable
    # until a PDF has been parsed.
    source_resume_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Every role belongs to exactly one user. ondelete="CASCADE" removes the role
    # automatically (at the database level) if its owner is deleted.
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    owner: Mapped["User"] = relationship(back_populates="roles")

    # One role has many drafts (usually one, but we keep a regeneration history).
    drafts: Mapped[List["Draft"]] = relationship(
        back_populates="role",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Draft.created_at.desc()",   # newest draft first when iterated
    )

    @property
    def has_source_resume(self) -> bool:
        """Whether a resume PDF has been parsed and stored for this role.

        ``RoleRead`` exposes this boolean instead of the full text so the roles
        list can show an "uploaded" indicator without shipping the entire resume
        to the client.
        """
        return self.source_resume_text is not None

    def __repr__(self) -> str:
        return f"<Role id={self.id} job_title={self.job_title!r} company={self.company!r}>"
