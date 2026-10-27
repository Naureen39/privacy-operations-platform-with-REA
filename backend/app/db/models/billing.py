import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    Base,
    TenantMixin,
    TimestampMixin,
    UuidPkMixin,
    enum_type,
    jsonb_default,
)
from app.db.enums import InvoiceLineKind, InvoiceStatus, SubscriptionStatus, UsageKind


class Plan(UuidPkMixin, Base):
    """Shared price list. Amounts are integer cents."""

    __tablename__ = "plans"

    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    monthly_fee_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    included_systems: Mapped[int] = mapped_column(Integer, nullable=False)
    included_requests: Mapped[int] = mapped_column(Integer, nullable=False)
    extra_system_cents: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    extra_request_cents: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class Subscription(UuidPkMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "subscriptions"

    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        enum_type(SubscriptionStatus),
        nullable=False,
        server_default=SubscriptionStatus.ACTIVE.value,
    )
    base_fee_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[date] = mapped_column(Date, nullable=False)
    ended_at: Mapped[date | None] = mapped_column(Date)
    is_simulated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )


class UsageEvent(UuidPkMixin, TenantMixin, Base):
    __tablename__ = "usage_events"

    kind: Mapped[UsageKind] = mapped_column(enum_type(UsageKind), nullable=False)
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    system_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("systems.id", ondelete="SET NULL")
    )
    provider: Mapped[str | None] = mapped_column(String(40))
    is_simulated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    __table_args__ = (
        Index("ix_usage_events_org_id_kind_occurred_at", "org_id", "kind", "occurred_at"),
    )


class Invoice(UuidPkMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "invoices"

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    number: Mapped[str] = mapped_column(String(40), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(
        enum_type(InvoiceStatus),
        nullable=False,
        server_default=InvoiceStatus.OPEN.value,
    )
    total_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_simulated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    __table_args__ = (
        UniqueConstraint("org_id", "number"),
        Index("ix_invoices_org_id_period_start", "org_id", "period_start"),
    )


class InvoiceLine(UuidPkMixin, TenantMixin, Base):
    __tablename__ = "invoice_lines"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[InvoiceLineKind] = mapped_column(enum_type(InvoiceLineKind), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        CheckConstraint("amount_cents = quantity * unit_cents", name="amount_matches"),
    )


class DailyMetric(Base):
    """Platform wide revenue snapshot, one row per day. Not tenant scoped (see docs)."""

    __tablename__ = "daily_metrics"

    metric_date: Mapped[date] = mapped_column(Date, primary_key=True)
    mrr_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    new_mrr_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    expansion_mrr_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    contraction_mrr_cents: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    churned_mrr_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    usage_revenue_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    accounts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    systems: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    requests: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tokens_by_provider: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=jsonb_default("{}")
    )
    failovers: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cache_hits: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_simulated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    paying_accounts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    arpa_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    # Trailing twelve months net revenue retention and the month's gross churn, in basis points.
    nrr_bp: Mapped[int | None] = mapped_column(Integer)
    gross_churn_bp: Mapped[int | None] = mapped_column(Integer)


class ComplianceDailyMetric(UuidPkMixin, TenantMixin, Base):
    __tablename__ = "compliance_daily_metrics"

    metric_date: Mapped[date] = mapped_column(Date, nullable=False)
    approved_records: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    stale_records: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    open_findings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=jsonb_default("{}")
    )
    assessments_by_status: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=jsonb_default("{}")
    )
    requests_open: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    requests_overdue: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    discovery_confidence_avg: Mapped[float | None] = mapped_column(Numeric(4, 3))
    rea_run_duration_ms_avg: Mapped[int | None] = mapped_column(Integer)
    is_simulated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    __table_args__ = (UniqueConstraint("org_id", "metric_date"),)
