"""billing: the illustrative price list and the extra figures of the daily snapshot

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-27 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Illustrative prices in US cents (see docs/architecture.md): code, name, fee, included systems,
# included requests per month, price per extra system, price per extra request.
PLANS = [
    ("starter", "Starter", 0, 3, 5, 0, 0),
    ("professional", "Professional", 39900, 25, 50, 1500, 800),
    ("enterprise", "Enterprise", 180000, 150, 500, 600, 400),
]


def upgrade() -> None:
    for column in ("paying_accounts", "arpa_cents", "nrr_bp", "gross_churn_bp"):
        op.add_column(
            "daily_metrics",
            sa.Column(
                column,
                sa.BigInteger() if column == "arpa_cents" else sa.Integer(),
                server_default="0" if column in ("paying_accounts", "arpa_cents") else None,
                nullable=column in ("nrr_bp", "gross_churn_bp"),
            ),
        )
    op.create_index("ix_invoices_org_id_period_start", "invoices", ["org_id", "period_start"])
    bind = op.get_bind()
    for code, name, fee, systems, requests, extra_system, extra_request in PLANS:
        bind.execute(
            sa.text(
                "INSERT INTO plans (code, name, monthly_fee_cents, included_systems, included_requests, "
                "extra_system_cents, extra_request_cents, is_active) "
                "VALUES (:c, :n, :f, :s, :r, :es, :er, true) ON CONFLICT (code) DO NOTHING"
            ),
            {
                "c": code,
                "n": name,
                "f": fee,
                "s": systems,
                "r": requests,
                "es": extra_system,
                "er": extra_request,
            },
        )


def downgrade() -> None:
    op.drop_index("ix_invoices_org_id_period_start", table_name="invoices")
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM plans WHERE code IN ('starter', 'professional', 'enterprise') AND NOT EXISTS (SELECT 1 FROM subscriptions s WHERE s.plan_id = plans.id)"
        )
    )
    for column in ("gross_churn_bp", "nrr_bp", "arpa_cents", "paying_accounts"):
        op.drop_column("daily_metrics", column)
