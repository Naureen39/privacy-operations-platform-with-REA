import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    Base,
    TenantMixin,
    TimestampMixin,
    UuidPkMixin,
    enum_type,
    jsonb_default,
)
from app.db.enums import ActivityStatus, DpiaStatus


class ProcessingActivity(UuidPkMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "processing_activities"

    name: Mapped[str] = mapped_column(String(300), nullable=False)
    purposes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    data_subjects: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    data_categories: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    recipients: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=jsonb_default("[]")
    )
    transfers: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=jsonb_default("[]")
    )
    retention: Mapped[str | None] = mapped_column(Text)
    security_measures: Mapped[str | None] = mapped_column(Text)
    lawful_basis: Mapped[str | None] = mapped_column(String(80))
    special_category_condition: Mapped[str | None] = mapped_column(String(200))
    citations: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=jsonb_default("{}")
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[ActivityStatus] = mapped_column(
        enum_type(ActivityStatus),
        nullable=False,
        server_default=ActivityStatus.DRAFT.value,
    )
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    next_review_date: Mapped[date | None] = mapped_column(Date)


class ActivityVersion(UuidPkMixin, TenantMixin, Base):
    __tablename__ = "activity_versions"

    activity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("processing_activities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    change_summary: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (UniqueConstraint("activity_id", "version"),)


class ActivitySystem(TenantMixin, Base):
    __tablename__ = "activity_systems"

    activity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("processing_activities.id", ondelete="CASCADE"), nullable=False
    )
    system_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("systems.id", ondelete="CASCADE"), nullable=False, index=True
    )

    __table_args__ = (PrimaryKeyConstraint("activity_id", "system_id"),)


class Dpia(UuidPkMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "dpias"

    activity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("processing_activities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[DpiaStatus] = mapped_column(
        enum_type(DpiaStatus), nullable=False, server_default=DpiaStatus.DRAFT.value
    )
    trigger_scores: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=jsonb_default("{}")
    )
    criteria_met: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    description: Mapped[str | None] = mapped_column(Text)
    necessity_proportionality: Mapped[str | None] = mapped_column(Text)
    residual_risk: Mapped[str | None] = mapped_column(String(40))
    officer_opinion: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class DpiaRisk(UuidPkMixin, TenantMixin, Base):
    __tablename__ = "dpia_risks"

    dpia_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dpias.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    likelihood: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[int] = mapped_column(Integer, nullable=False)
    mitigation: Mapped[str | None] = mapped_column(Text)
    residual_likelihood: Mapped[int | None] = mapped_column(Integer)
    residual_severity: Mapped[int | None] = mapped_column(Integer)
    citation: Mapped[str | None] = mapped_column(String(200))

    __table_args__ = (
        CheckConstraint("likelihood BETWEEN 1 AND 5", name="likelihood_range"),
        CheckConstraint("severity BETWEEN 1 AND 5", name="severity_range"),
        CheckConstraint(
            "residual_likelihood IS NULL OR residual_likelihood BETWEEN 1 AND 5",
            name="residual_likelihood_range",
        ),
        CheckConstraint(
            "residual_severity IS NULL OR residual_severity BETWEEN 1 AND 5",
            name="residual_severity_range",
        ),
    )
