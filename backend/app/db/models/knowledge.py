import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, UuidPkMixin, enum_type, jsonb_default
from app.db.enums import DocumentType
from app.db.models.inventory import EMBEDDING_DIMENSIONS

_TSV_EXPR = "to_tsvector('english', text)"


class Document(UuidPkMixin, TenantMixin, Base):
    __tablename__ = "documents"

    system_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("systems.id", ondelete="CASCADE"), index=True
    )
    doc_type: Mapped[DocumentType] = mapped_column(enum_type(DocumentType), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    source_uri: Mapped[str | None] = mapped_column(Text)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    doc_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=jsonb_default("{}")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class DocumentChunk(UuidPkMixin, TenantMixin, Base):
    __tablename__ = "document_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    system_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("systems.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    heading: Mapped[str | None] = mapped_column(String(300))
    page: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    tsv: Mapped[Any] = mapped_column(TSVECTOR, Computed(_TSV_EXPR, persisted=True))

    __table_args__ = (
        Index(
            "ix_document_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_document_chunks_tsv", "tsv", postgresql_using="gin"),
    )


class RegulationChunk(UuidPkMixin, Base):
    """Shared, read only corpus (GDPR text). Not tenant scoped."""

    __tablename__ = "regulation_chunks"

    regulation: Mapped[str] = mapped_column(String(40), nullable=False, server_default="GDPR")
    chapter: Mapped[str | None] = mapped_column(String(200))
    article: Mapped[int | None] = mapped_column(Integer, index=True)
    paragraph: Mapped[str | None] = mapped_column(String(20))
    title: Mapped[str | None] = mapped_column(String(300))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    tsv: Mapped[Any] = mapped_column(TSVECTOR, Computed(_TSV_EXPR, persisted=True))

    __table_args__ = (
        Index(
            "ix_regulation_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_regulation_chunks_tsv", "tsv", postgresql_using="gin"),
    )
