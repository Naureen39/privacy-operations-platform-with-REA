"""authentication support: organization settings and refresh token organization

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-19 17:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "settings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    # Refresh tokens are issued for one organization (the session organization).
    op.execute("DELETE FROM refresh_tokens")
    op.add_column("refresh_tokens", sa.Column("session_org_id", sa.Uuid(), nullable=False))
    op.create_foreign_key(
        op.f("fk_refresh_tokens_session_org_id_organizations"),
        "refresh_tokens",
        "organizations",
        ["session_org_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_refresh_tokens_session_org_id_organizations"),
        "refresh_tokens",
        type_="foreignkey",
    )
    op.drop_column("refresh_tokens", "session_org_id")
    op.drop_column("organizations", "settings")
