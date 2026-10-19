"""Authentication and authorization dependencies.

Every protected route declares its roles with `require_role(...)`. The backend is the
authority: roles come from the memberships table on each request, not from the token,
so removing a membership or deactivating a user takes effect immediately.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import insert, select

from app.api.tenancy import get_tenant_db
from app.core.config import Settings
from app.core.security import Claims, TokenError, decode_access_token
from app.db.enums import Role
from app.db.models import AuditLog, Membership, System, User
from app.db.session import TenantContext, TenantSession

ACCESS_COOKIE = "pl_access"
REFRESH_COOKIE = "pl_refresh"
CSRF_COOKIE = "pl_csrf"
CSRF_HEADER = "x-csrf-token"

ALL_ROLES = (Role.ADMIN, Role.ANALYST, Role.SYSTEM_OWNER, Role.VIEWER)


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    org_id: uuid.UUID
    role: Role
    email: str
    full_name: str


def app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_claims(request: Request, settings: Settings = Depends(app_settings)) -> Claims:
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    assert settings.jwt_secret is not None  # noqa: S101  (validated at startup)
    try:
        claims = decode_access_token(settings.jwt_secret.get_secret_value(), token)
    except TokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session") from exc
    request.state.tenant = TenantContext(claims.org_id, claims.user_id)
    return claims


def get_principal(
    claims: Claims = Depends(get_claims), db: TenantSession = Depends(get_tenant_db)
) -> Principal:
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == claims.user_id, Membership.org_id == claims.org_id
        )
    )
    user = db.get(User, claims.user_id)
    if membership is None or user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")
    return Principal(user.id, claims.org_id, membership.role, user.email, user.full_name)


def require_role(*roles: Role) -> Callable[..., Principal]:
    allowed = frozenset(roles)

    def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return principal

    dependency.allowed_roles = allowed  # type: ignore[attr-defined]  # read by the route audit test
    return dependency


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def write_audit(
    db: TenantSession,
    request: Request,
    action: str,
    *,
    principal: Principal | None = None,
    entity_type: str | None = None,
    entity_id: object | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    # Core insert without RETURNING: rows with no organization are insert-only for the
    # application role, and RETURNING would apply the SELECT policy to them.
    db.execute(
        insert(AuditLog).values(
            org_id=principal.org_id if principal else None,
            actor_user_id=principal.user_id if principal else None,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            ip_address=client_ip(request),
            details=details or {},
        )
    )


def get_visible_system(db: TenantSession, principal: Principal, system_id: uuid.UUID) -> System:
    """Load a system, hiding it (404) from a system owner who does not own it."""
    system = db.get(System, system_id)
    if system is None or (
        principal.role is Role.SYSTEM_OWNER and system.owner_user_id != principal.user_id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "System not found")
    return system
