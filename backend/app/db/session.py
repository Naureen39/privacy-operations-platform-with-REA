"""Engine and tenant aware sessions.

Row Level Security reads two transaction local settings, `app.org_id` and
`app.user_id`. TenantSession re-applies them at the start of every transaction, so a
commit in the middle of a unit of work cannot leave later statements without a tenant.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, SessionTransaction, sessionmaker

from app.core.config import get_settings

_TENANT_KEY = "tenant_context"


@dataclass(frozen=True)
class TenantContext:
    org_id: uuid.UUID
    user_id: uuid.UUID | None = None


class TenantSession(Session):
    """Session whose transactions always carry the tenant settings."""


@event.listens_for(TenantSession, "after_begin")
def _apply_tenant_settings(
    session: Session, transaction: SessionTransaction, connection: object
) -> None:
    context: TenantContext | None = session.info.get(_TENANT_KEY)
    org = str(context.org_id) if context else ""
    user = str(context.user_id) if context and context.user_id else ""
    connection.execute(  # type: ignore[attr-defined]
        text("SELECT set_config('app.org_id', :org, true), set_config('app.user_id', :usr, true)"),
        {"org": org, "usr": user},
    )


def make_engine(url: str | None = None, *, pool_size: int | None = None) -> Engine:
    settings = get_settings()
    return create_engine(
        url or settings.database_url,
        pool_size=pool_size or settings.db_pool_size,
        pool_pre_ping=True,
    )


def make_session_factory(engine: Engine) -> sessionmaker[TenantSession]:
    return sessionmaker(engine, class_=TenantSession, expire_on_commit=False)


def set_tenant(session: Session, context: TenantContext) -> None:
    """Bind a session to a tenant. Applies immediately and to all later transactions."""
    session.info[_TENANT_KEY] = context
    session.execute(
        text("SELECT set_config('app.org_id', :org, true), set_config('app.user_id', :usr, true)"),
        {"org": str(context.org_id), "usr": str(context.user_id) if context.user_id else ""},
    )


@contextmanager
def tenant_session(
    factory: sessionmaker[TenantSession], context: TenantContext
) -> Iterator[TenantSession]:
    """Open a session bound to one tenant. Commits on success, rolls back on error."""
    session = factory()
    try:
        session.info[_TENANT_KEY] = context
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
