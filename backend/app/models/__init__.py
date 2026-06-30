"""SQLAlchemy ORM models: the database schema as Python classes.

Importing this package imports every model module, which is what registers each
table on the shared ``Base.metadata``. Anything that needs the full schema (most
importantly Alembic's autogenerate) must import ``app.models`` so no table is
left out.

    user   authenticated accounts (JWT login)
    role   a targeted job application (job title, company, JD text)
    draft  the generated artifacts for a role (resume rewrite, cover letter, Q&A)
"""

from app.core.database import Base
from app.models.draft import Draft
from app.models.role import Role
from app.models.user import User

__all__ = ["Base", "User", "Role", "Draft"]
