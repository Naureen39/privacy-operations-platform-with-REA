import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, UuidPkMixin, enum_type, jsonb_default
from app.db.enums import EvidenceKind, Extractor, JobState, RecipientRole, ReviewStatus

EMBEDDING_DIMENSIONS = 384


class System(UuidPkMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "systems"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[JobState] = mapped_column(
        enum_type(JobState), nullable=False, server_default=JobState.CREATED.value
    )
    last_discovery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("org_id", "slug"),)


class EvidenceItem(UuidPkMixin, TenantMixin, Base):
    __tablename__ = "evidence_items"

    system_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("systems.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[EvidenceKind] = mapped_column(enum_type(EvidenceKind), nullable=False)
    extractor: Mapped[Extractor | None] = mapped_column(enum_type(Extractor))
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    encrypted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class DiscoveryRun(UuidPkMixin, TenantMixin, Base):
    __tablename__ = "discovery_runs"

    system_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("systems.id", ondelete="CASCADE"), nullable=False, index=True
    )
    state: Mapped[JobState] = mapped_column(
        enum_type(JobState), nullable=False, server_default=JobState.DISCOVERING.value
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class DiscoveryEvidence(UuidPkMixin, TenantMixin, Base):
    """Raw extractor output. Every stored fact points here (or to a document chunk)."""

    __tablename__ = "discovery_evidence"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("discovery_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    evidence_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("evidence_items.id", ondelete="SET NULL"), index=True
    )
    extractor: Mapped[Extractor] = mapped_column(enum_type(Extractor), nullable=False)
    command: Mapped[str | None] = mapped_column(Text)
    rea_version: Mapped[str | None] = mapped_column(String(40))
    raw_output: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="ok")
    error: Mapped[str | None] = mapped_column(Text)
    raw_sha256: Mapped[str | None] = mapped_column(String(64))
    raw_truncated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


_PROVENANCE = "evidence_id IS NOT NULL OR source_chunk_id IS NOT NULL"


class DataElement(UuidPkMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "data_elements"

    system_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("systems.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    path: Mapped[str | None] = mapped_column(Text)
    data_type: Mapped[str | None] = mapped_column(String(80))
    pattern_class: Mapped[str | None] = mapped_column(String(80))
    category: Mapped[str | None] = mapped_column(String(120))
    special_category: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    special_category_label: Mapped[str | None] = mapped_column(String(120))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    review_status: Mapped[ReviewStatus] = mapped_column(
        enum_type(ReviewStatus),
        nullable=False,
        server_default=ReviewStatus.PENDING.value,
    )
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("discovery_evidence.id", ondelete="SET NULL"), index=True
    )
    source_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="SET NULL")
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    source_kind: Mapped[str | None] = mapped_column(String(40))
    context: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=jsonb_default("{}")
    )

    __table_args__ = (
        CheckConstraint(_PROVENANCE, name="has_provenance"),
        Index("ix_data_elements_system_id_name", "system_id", "name"),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_range"
        ),
        Index(
            "ix_data_elements_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class Recipient(UuidPkMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "recipients"

    system_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("systems.id", ondelete="CASCADE"), nullable=False, index=True
    )
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    vendor: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[RecipientRole] = mapped_column(
        enum_type(RecipientRole),
        nullable=False,
        server_default=RecipientRole.UNKNOWN.value,
    )
    country: Mapped[str | None] = mapped_column(String(80))
    purpose: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(120))
    agreement_on_file: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    safeguard: Mapped[str | None] = mapped_column(String(200))
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("discovery_evidence.id", ondelete="SET NULL"), index=True
    )
    source_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="SET NULL")
    )
    context: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=jsonb_default("{}")
    )

    __table_args__ = (
        CheckConstraint(_PROVENANCE, name="has_provenance"),
        Index("ix_recipients_system_id_domain", "system_id", "domain"),
    )


class Technology(UuidPkMixin, TenantMixin, Base):
    __tablename__ = "technologies"

    system_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("systems.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str | None] = mapped_column(String(80))
    version: Mapped[str | None] = mapped_column(String(80))
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("discovery_evidence.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    context: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=jsonb_default("{}")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
