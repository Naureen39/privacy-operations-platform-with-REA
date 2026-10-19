import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, UuidPkMixin, enum_type, jsonb_default
from app.db.enums import LeadKind, Role


class Organization(UuidPkMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    industry: Mapped[str | None] = mapped_column(String(80))
    region: Mapped[str | None] = mapped_column(String(80))
    is_simulated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )


class User(UuidPkMixin, TimestampMixin, Base):
    """Identity record shared across organizations (a user can belong to several)."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("uq_users_email_lower", func.lower(email), unique=True),)


class Membership(UuidPkMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "memberships"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[Role] = mapped_column(enum_type(Role), nullable=False)

    __table_args__ = (UniqueConstraint("org_id", "user_id"),)


class RefreshToken(UuidPkMixin, Base):
    """Rotating refresh tokens, stored hashed. Looked up by hash before the tenant is known."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    family_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class AuditLog(UuidPkMixin, Base):
    """Append only. org_id is nullable so that unattributed events (failed logins) can be kept."""

    __tablename__ = "audit_log"

    org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        server_default=text("nullif(current_setting('app.org_id', true), '')::uuid"),
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(80))
    entity_id: Mapped[str | None] = mapped_column(String(80))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=jsonb_default("{}")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        Index("ix_audit_log_org_id_created_at", "org_id", "created_at"),
        Index("ix_audit_log_action", "action"),
    )


class Lead(UuidPkMixin, TenantMixin, Base):
    """Contact and demo requests. Owned by the host organization, visible to its admins."""

    __tablename__ = "leads"

    kind: Mapped[LeadKind] = mapped_column(enum_type(LeadKind), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    company: Mapped[str | None] = mapped_column(String(200))
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


__all__ = [
    "AuditLog",
    "Lead",
    "Membership",
    "Organization",
    "RefreshToken",
    "User",
]
