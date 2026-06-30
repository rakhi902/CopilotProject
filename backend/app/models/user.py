"""The ``User`` model: an authenticated account.

A user owns many roles (job applications). Authentication uses a hashed password
plus JWT access tokens; the hashing and token logic lives in ``app.core.security``,
while this model just stores the resulting password hash.
"""

from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin

# Imported only for type-checkers and IDEs. At runtime SQLAlchemy resolves the
# "Role" relationship target by class name from its registry, so no real import
# is needed here, which also avoids a circular import between the model modules.
if TYPE_CHECKING:
    from app.models.role import Role


class User(TimestampMixin, Base):
    """A registered account that can create roles and generate drafts."""

    __tablename__ = "users"

    # Surrogate primary key (indexed automatically as the PK).
    id: Mapped[int] = mapped_column(primary_key=True)

    # Login identifier. Unique and indexed because we look users up by email on
    # every sign-in. 320 chars is the maximum length of a valid email address.
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)

    # The bcrypt hash of the password, never the plaintext. 255 chars holds a
    # bcrypt digest (about 60 chars) with plenty of room to spare.
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    # Optional display name shown in the UI.
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Soft-disable switch: an inactive user keeps their data but can't log in.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # One user has many roles. cascade="all, delete-orphan" means deleting a user
    # also removes their roles (and, through them, those roles' drafts).
    # passive_deletes lets the database's own ON DELETE CASCADE do the work
    # instead of loading every child into memory first.
    roles: Mapped[List["Role"]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"
