"""impact assessment screenings

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-22 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "processledger_app"
TABLE = "dpia_screenings"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("activity_id", sa.Uuid(), nullable=False),
        sa.Column(
            "criteria", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("criteria_met", sa.Integer(), server_default="0", nullable=False),
        sa.Column("criteria_unknown", sa.Integer(), server_default="0", nullable=False),
        sa.Column("threshold", sa.Integer(), server_default="2", nullable=False),
        sa.Column("required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "inputs", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("criteria_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("screened_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["activity_id"],
            ["processing_activities.id"],
            name=op.f("fk_dpia_screenings_activity_id_processing_activities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_dpia_screenings_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["screened_by"],
            ["users.id"],
            name=op.f("fk_dpia_screenings_screened_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dpia_screenings")),
        sa.UniqueConstraint("activity_id", name=op.f("uq_dpia_screenings_activity_id")),
    )
    op.create_index(op.f("ix_dpia_screenings_org_id"), TABLE, ["org_id"], unique=False)
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {TABLE} "
        "USING (org_id = app_current_org()) WITH CHECK (org_id = app_current_org())"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {TABLE} TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"DROP POLICY tenant_isolation ON {TABLE}")
    op.drop_table(TABLE)
