import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, MetaData, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Server side expression that fills org_id from the per request tenant setting.
CURRENT_ORG_SQL = "nullif(current_setting('app.org_id', true), '')::uuid"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def enum_type(enum_cls: type[StrEnum]) -> Enum:
    """Store a StrEnum as a varchar with a CHECK constraint (no native PG enum)."""
    return Enum(
        enum_cls,
        name=enum_cls.__name__.lower(),
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda e: [m.value for m in e],
    )


class UuidPkMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=text("now()"),
        nullable=False,
    )


class TenantMixin:
    """Adds org_id. The Row Level Security policy in migration 0002 binds it to app.org_id."""

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        default=None,
        server_default=text(CURRENT_ORG_SQL),
    )


def jsonb_default(value: Any) -> Any:
    return text(f"'{value}'::jsonb")
