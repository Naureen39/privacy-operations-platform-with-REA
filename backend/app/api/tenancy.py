"""Per request tenancy dependency.

Phase 2 (authentication) populates `request.state.tenant` from the verified access
token. This module only consumes it: a request without a tenant never reaches the
database, and a request with one gets a session bound to that tenant.
"""

from collections.abc import Iterator

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import sessionmaker

from app.db.session import TenantContext, TenantSession, tenant_session


def get_tenant_context(request: Request) -> TenantContext:
    context = getattr(request.state, "tenant", None)
    if not isinstance(context, TenantContext):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    return context


def get_session_factory(request: Request) -> sessionmaker[TenantSession]:
    factory: sessionmaker[TenantSession] = request.app.state.session_factory
    return factory


def get_tenant_db(request: Request) -> Iterator[TenantSession]:
    """FastAPI dependency yielding a session bound to the request's tenant."""
    context = get_tenant_context(request)
    with tenant_session(get_session_factory(request), context) as session:
        yield session
