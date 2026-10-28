"""revenue breakdowns: the platform wide figures that need more than a daily row

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-28 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "processledger_app"


def upgrade() -> None:
    op.create_table(
        "revenue_breakdowns",
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_simulated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("as_of", name=op.f("pk_revenue_breakdowns")),
    )
    # Platform wide, like daily_metrics: the application role can read it and nothing else. The
    # nightly job writes it with the owner connection.
    op.execute(f"GRANT SELECT ON revenue_breakdowns TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON revenue_breakdowns FROM {APP_ROLE}")
    op.drop_table("revenue_breakdowns")
