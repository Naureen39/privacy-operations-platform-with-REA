import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, UuidPkMixin, enum_type
from app.db.enums import LlmCallStatus


class LlmCache(UuidPkMixin, TenantMixin, Base):
    """Answers keyed by the SHA-256 of the normalized request."""

    __tablename__ = "llm_cache"

    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    task: Mapped[str] = mapped_column(String(80), nullable=False)
    response: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sql_text("now()"), nullable=False
    )

    __table_args__ = (UniqueConstraint("org_id", "request_hash"),)


class LlmCall(UuidPkMixin, TenantMixin, Base):
    __tablename__ = "llm_calls"

    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    task: Mapped[str] = mapped_column(String(80), nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cached_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[LlmCallStatus] = mapped_column(enum_type(LlmCallStatus), nullable=False)
    cache_hit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("false")
    )
    system_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("systems.id", ondelete="SET NULL"), index=True
    )
    dpia_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("dpias.id", ondelete="SET NULL"))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sql_text("now()"), nullable=False
    )

    __table_args__ = (Index("ix_llm_calls_org_id_created_at", "org_id", "created_at"),)
