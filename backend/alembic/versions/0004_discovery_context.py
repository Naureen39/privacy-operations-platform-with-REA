"""discovery: context on extracted facts and integrity data on raw extractor output

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-20 17:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.add_column(
        "data_elements",
        sa.Column("context", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.add_column("data_elements", sa.Column("source_kind", sa.String(length=40), nullable=True))
    op.add_column(
        "recipients",
        sa.Column("context", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.add_column(
        "technologies",
        sa.Column("context", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.add_column(
        "discovery_evidence", sa.Column("raw_sha256", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "discovery_evidence",
        sa.Column("raw_truncated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_index(
        "ix_data_elements_system_id_name", "data_elements", ["system_id", "name"], unique=False
    )
    op.create_index(
        "ix_recipients_system_id_domain", "recipients", ["system_id", "domain"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_recipients_system_id_domain", table_name="recipients")
    op.drop_index("ix_data_elements_system_id_name", table_name="data_elements")
    op.drop_column("discovery_evidence", "raw_truncated")
    op.drop_column("discovery_evidence", "raw_sha256")
    op.drop_column("technologies", "context")
    op.drop_column("recipients", "context")
    op.drop_column("data_elements", "source_kind")
    op.drop_column("data_elements", "context")
