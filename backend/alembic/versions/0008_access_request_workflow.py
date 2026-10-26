"""access request workflow: identifier type, reference, identity checklist, dates

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-23 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "access_requests"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            "identifier_type",
            sa.String(length=20),
            server_default=sa.text("'email'"),
            nullable=False,
        ),
    )
    op.add_column(TABLE, sa.Column("reference", sa.String(length=40), nullable=True))
    op.add_column(
        TABLE,
        sa.Column(
            "identity_checklist",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )
    op.add_column(TABLE, sa.Column("rejection_reason", sa.Text(), nullable=True))
    op.add_column(TABLE, sa.Column("searched_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(TABLE, sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint(
        op.f("uq_access_requests_org_id_reference"), TABLE, ["org_id", "reference"]
    )


def downgrade() -> None:
    op.drop_constraint(op.f("uq_access_requests_org_id_reference"), TABLE, type_="unique")
    for column in (
        "responded_at",
        "searched_at",
        "rejection_reason",
        "identity_checklist",
        "reference",
        "identifier_type",
    ):
        op.drop_column(TABLE, column)
