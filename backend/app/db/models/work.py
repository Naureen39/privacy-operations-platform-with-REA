import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
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
from app.db.enums import (
    ApprovalStatus,
    FindingSeverity,
    FindingStatus,
    JobStatus,
    RequestStatus,
    ResponseStatus,
    TaskStatus,
)


class Finding(UuidPkMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "findings"

    system_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("systems.id", ondelete="CASCADE"), index=True
    )
    activity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("processing_activities.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[FindingSeverity] = mapped_column(enum_type(FindingSeverity), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    evidence_refs: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=jsonb_default("[]")
    )
    suggested_fix: Mapped[str | None] = mapped_column(Text)
    status: Mapped[FindingStatus] = mapped_column(
        enum_type(FindingStatus),
        nullable=False,
        server_default=FindingStatus.OPEN.value,
    )
    dedupe_key: Mapped[str | None] = mapped_column(String(200))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("org_id", "dedupe_key"),
        Index("ix_findings_org_id_status_severity", "org_id", "status", "severity"),
    )


class Task(UuidPkMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "tasks"

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    system_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("systems.id", ondelete="CASCADE"), index=True
    )
    finding_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("findings.id", ondelete="SET NULL")
    )
    status: Mapped[TaskStatus] = mapped_column(
        enum_type(TaskStatus), nullable=False, server_default=TaskStatus.OPEN.value
    )
    due_date: Mapped[date | None] = mapped_column(Date)
    dedupe_key: Mapped[str | None] = mapped_column(String(200))

    __table_args__ = (UniqueConstraint("org_id", "dedupe_key"),)


class Job(UuidPkMixin, TimestampMixin, TenantMixin, Base):
    """A background run, for example the onboarding of a system through its stages."""

    __tablename__ = "jobs"

    system_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("systems.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False, server_default="onboarding")
    state: Mapped[JobStatus] = mapped_column(
        enum_type(JobStatus), nullable=False, server_default=JobStatus.QUEUED.value
    )
    stages: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=jsonb_default("{}")
    )
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=jsonb_default("{}")
    )
    result: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=jsonb_default("{}")
    )
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobEvent(TenantMixin, Base):
    """One transition of a job. `seq` orders events for the progress stream."""

    __tablename__ = "job_events"

    seq: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    system_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("systems.id", ondelete="CASCADE")
    )
    stage: Mapped[str | None] = mapped_column(String(40))
    event: Mapped[str] = mapped_column(String(30), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=jsonb_default("{}")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class Notification(UuidPkMixin, TenantMixin, Base):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    entity_type: Mapped[str | None] = mapped_column(String(80))
    entity_id: Mapped[uuid.UUID | None] = mapped_column()
    dedupe_key: Mapped[str | None] = mapped_column(String(200))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (UniqueConstraint("org_id", "user_id", "dedupe_key"),)


class Approval(UuidPkMixin, TenantMixin, Base):
    __tablename__ = "approvals"

    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[ApprovalStatus] = mapped_column(
        enum_type(ApprovalStatus),
        nullable=False,
        server_default=ApprovalStatus.PENDING.value,
    )
    decision_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_approvals_entity", "entity_type", "entity_id"),)


class Comment(UuidPkMixin, TenantMixin, Base):
    __tablename__ = "comments"

    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (Index("ix_comments_entity", "entity_type", "entity_id"),)


class AccessRequest(UuidPkMixin, TimestampMixin, TenantMixin, Base):
    """Subject identifiers are stored only as an HMAC hash."""

    __tablename__ = "access_requests"

    subject_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    received_date: Mapped[date] = mapped_column(Date, nullable=False)
    deadline_date: Mapped[date] = mapped_column(Date, nullable=False)
    extended: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    extension_months: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    extension_reason: Mapped[str | None] = mapped_column(Text)
    identity_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    status: Mapped[RequestStatus] = mapped_column(
        enum_type(RequestStatus),
        nullable=False,
        server_default=RequestStatus.RECEIVED.value,
    )
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    identifier_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'email'")
    )
    reference: Mapped[str | None] = mapped_column(String(40))
    identity_checklist: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=jsonb_default("{}")
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    searched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("org_id", "reference"),)


class RequestResult(UuidPkMixin, TenantMixin, Base):
    __tablename__ = "request_results"

    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("access_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    system_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("systems.id", ondelete="CASCADE"), nullable=False
    )
    table_name: Mapped[str] = mapped_column(String(200), nullable=False)
    column_name: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(120))
    match_count: Mapped[int] = mapped_column(Integer, nullable=False)
    disclosure_approved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class RequestResponse(UuidPkMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "request_responses"

    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("access_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    cover_note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ResponseStatus] = mapped_column(
        enum_type(ResponseStatus),
        nullable=False,
        server_default=ResponseStatus.DRAFT.value,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (UniqueConstraint("request_id", "version"),)
