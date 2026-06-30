"""add role application_status and jd_url

Adds two columns to ``roles``:
  * ``application_status`` -- the user-managed pipeline state (Not Applied /
    Applied / Interviewing / Rejected); NOT NULL, defaults to "Not Applied"
    (the server_default also back-fills any pre-existing rows).
  * ``jd_url`` -- the source URL a JD was scraped from, when supplied; nullable.

Revision ID: c7e1a9b34d20
Revises: a040ad27ba72
Create Date: 2026-06-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c7e1a9b34d20"
down_revision: Union[str, None] = "a040ad27ba72"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply this migration (add the two role columns)."""
    with op.batch_alter_table("roles", schema=None) as batch_op:
        batch_op.add_column(sa.Column("jd_url", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "application_status",
                sa.String(length=20),
                nullable=False,
                # Quoted literal so existing rows back-fill to "Not Applied".
                server_default=sa.text("'Not Applied'"),
            )
        )


def downgrade() -> None:
    """Revert this migration (drop the two role columns)."""
    with op.batch_alter_table("roles", schema=None) as batch_op:
        batch_op.drop_column("application_status")
        batch_op.drop_column("jd_url")
