import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from slowapi import Limiter
from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from app.api.deps import (
    ACCESS_COOKIE,
    ALL_ROLES,
    CSRF_COOKIE,
    REFRESH_COOKIE,
    Principal,
    require_role,
    write_audit,
)
from app.api.schemas import LoginRequest, MembershipOut, MeOut, SessionOut, UserOut
from app.api.schemas_console import OrganizationChoice, SwitchIn
from app.api.tenancy import get_tenant_db
from app.core.config import Settings
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    hash_token,
    new_opaque_token,
    verify_password,
)
from app.db.enums import Role
from app.db.models import Membership, Organization, RefreshToken, User
from app.db.repositories import UserRepository
from app.db.session import TenantContext, TenantSession, set_tenant, tenant_session

REFRESH_PATH = "/api/v1/auth"


def _invalid_credentials() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")


def _set_cookies(response: Response, settings: Settings, access: str, refresh: str) -> None:
    secure = settings.cookie_secure
    response.set_cookie(
        ACCESS_COOKIE,
        access,
        max_age=settings.access_token_minutes * 60,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh,
        max_age=settings.refresh_token_days * 86400,
        httponly=True,
        secure=secure,
        samesite="lax",
        path=REFRESH_PATH,
    )
    # Readable by the frontend so it can echo the value in the X-CSRF-Token header.
    response.set_cookie(
        CSRF_COOKIE,
        secrets.token_urlsafe(32),
        max_age=settings.refresh_token_days * 86400,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )


def _clear_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH)
    response.delete_cookie(CSRF_COOKIE, path="/")


def _issue_refresh(
    s: TenantSession,
    settings: Settings,
    user_id: uuid.UUID,
    org_id: uuid.UUID,
    family: uuid.UUID,
) -> str:
    token = new_opaque_token()
    s.add(
        RefreshToken(
            user_id=user_id,
            session_org_id=org_id,
            token_hash=hash_token(token),
            family_id=family,
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_days),
        )
    )
    return token


def _access(settings: Settings, user_id: uuid.UUID, org_id: uuid.UUID, role: Role) -> str:
    assert settings.jwt_secret is not None  # noqa: S101  (validated at startup)
    return create_access_token(
        settings.jwt_secret.get_secret_value(),
        user_id,
        org_id,
        role,
        settings.access_token_minutes,
    )


def _revoke_family(s: TenantSession, family_id: uuid.UUID) -> None:
    s.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


def build_router(limiter: Limiter, settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

    def factory_of(request: Request) -> sessionmaker[TenantSession]:
        factory: sessionmaker[TenantSession] = request.app.state.session_factory
        return factory

    @router.post("/login", response_model=SessionOut)
    @limiter.limit(settings.login_rate_limit)
    def login(request: Request, response: Response, body: LoginRequest) -> SessionOut:
        """Registration is disabled. Accounts are provisioned by an administrator or seed."""
        now = datetime.now(UTC)
        with tenant_session(factory_of(request), TenantContext()) as s:
            user = UserRepository(s).get_by_email(body.email.strip())
            locked = bool(user and user.locked_until and user.locked_until > now)
            usable = bool(user and user.is_active and not locked)
            # Always verify a hash so that timing does not reveal whether the account exists.
            password_ok = verify_password(
                user.password_hash if user and usable else DUMMY_PASSWORD_HASH,
                body.password,
            )
            if not (user and usable and password_ok):
                reason = "locked" if locked else "bad_credentials"
                if user and usable:
                    user.failed_login_count += 1
                    if user.failed_login_count >= settings.max_failed_logins:
                        user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
                        user.failed_login_count = 0
                        reason = "lockout_started"
                write_audit(
                    s, request, "auth.login_failed", entity_type="user",
                    entity_id=user.id if user else None, details={"reason": reason},
                )  # fmt: skip
                s.commit()
                raise _invalid_credentials()

            user.failed_login_count = 0
            user.locked_until = None
            user.last_login_at = now
            set_tenant(s, TenantContext(None, user.id))
            memberships = list(
                s.scalars(
                    select(Membership)
                    .where(Membership.user_id == user.id)
                    .order_by(Membership.created_at, Membership.org_id)
                )
            )
            chosen = next(
                (m for m in memberships if body.org_id in (None, m.org_id)),
                None,
            )
            if chosen is None:
                write_audit(
                    s, request, "auth.login_failed", entity_type="user", entity_id=user.id,
                    details={"reason": "no_membership"},
                )  # fmt: skip
                s.commit()
                raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to this organization")

            set_tenant(s, TenantContext(chosen.org_id, user.id))
            principal = Principal(user.id, chosen.org_id, chosen.role, user.email, user.full_name)
            write_audit(s, request, "auth.login", principal=principal, entity_type="user",
                        entity_id=user.id)  # fmt: skip
            refresh = _issue_refresh(s, settings, user.id, chosen.org_id, uuid.uuid4())
            s.commit()
            access = _access(settings, user.id, chosen.org_id, chosen.role)
            _set_cookies(response, settings, access, refresh)
            return SessionOut(
                user=UserOut(id=user.id, email=user.email, full_name=user.full_name),
                org_id=chosen.org_id,
                role=chosen.role,
                memberships=[MembershipOut(org_id=m.org_id, role=m.role) for m in memberships],
            )

    @router.post("/refresh", status_code=status.HTTP_204_NO_CONTENT)
    def refresh(request: Request, response: Response) -> None:
        """Rotate the refresh token. Presenting a rotated token revokes its whole family."""
        token = request.cookies.get(REFRESH_COOKIE)
        if not token:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
        now = datetime.now(UTC)
        with tenant_session(factory_of(request), TenantContext()) as s:
            row = s.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(token)))
            if row is None:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session")
            set_tenant(s, TenantContext(row.session_org_id, row.user_id))
            if row.revoked_at is not None:
                _revoke_family(s, row.family_id)
                write_audit(s, request, "auth.refresh_reuse_detected", entity_type="user",
                            entity_id=row.user_id)  # fmt: skip
                s.commit()
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session")
            user = s.get(User, row.user_id)
            membership = s.scalar(
                select(Membership).where(
                    Membership.user_id == row.user_id,
                    Membership.org_id == row.session_org_id,
                )
            )
            if row.expires_at <= now or user is None or not user.is_active or membership is None:
                _revoke_family(s, row.family_id)
                s.commit()
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session")

            row.revoked_at = now
            new_refresh = _issue_refresh(s, settings, user.id, row.session_org_id, row.family_id)
            s.commit()
            access = _access(settings, user.id, row.session_org_id, membership.role)
            _set_cookies(response, settings, access, new_refresh)

    @router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
    def logout(request: Request, response: Response) -> None:
        token = request.cookies.get(REFRESH_COOKIE)
        if token:
            with tenant_session(factory_of(request), TenantContext()) as s:
                row = s.scalar(
                    select(RefreshToken).where(RefreshToken.token_hash == hash_token(token))
                )
                if row is not None:
                    set_tenant(s, TenantContext(row.session_org_id, row.user_id))
                    _revoke_family(s, row.family_id)
                    principal = Principal(row.user_id, row.session_org_id, Role.VIEWER, "", "")
                    write_audit(s, request, "auth.logout", principal=principal,
                                entity_type="user", entity_id=row.user_id)  # fmt: skip
                    s.commit()
        _clear_cookies(response)

    @router.get("/me", response_model=MeOut)
    def me(principal: Principal = Depends(require_role(*ALL_ROLES))) -> MeOut:
        return MeOut(
            user=UserOut(
                id=principal.user_id,
                email=principal.email,
                full_name=principal.full_name,
            ),
            org_id=principal.org_id,
            role=principal.role,
            is_host=settings.leads_org_id is not None and principal.org_id == settings.leads_org_id,
        )

    @router.get("/organizations", response_model=list[OrganizationChoice])
    def organizations(
        principal: Principal = Depends(require_role(*ALL_ROLES)),
        s: TenantSession = Depends(get_tenant_db),
    ) -> list[OrganizationChoice]:
        """The organizations this person belongs to, for the organization switcher."""
        memberships = list(
            s.scalars(
                select(Membership)
                .where(Membership.user_id == principal.user_id)
                .order_by(Membership.created_at, Membership.org_id)
            )
        )
        choices = []
        for m in memberships:
            set_tenant(s, TenantContext(m.org_id, principal.user_id))
            name = s.scalar(select(Organization.name).where(Organization.id == m.org_id))
            choices.append(
                OrganizationChoice(
                    org_id=m.org_id, name=name or "Organization", role=m.role,
                    current=m.org_id == principal.org_id,
                )  # fmt: skip
            )
        set_tenant(s, TenantContext(principal.org_id, principal.user_id))
        return choices

    @router.post("/switch", response_model=SessionOut)
    def switch(
        request: Request,
        response: Response,
        body: SwitchIn,
        principal: Principal = Depends(require_role(*ALL_ROLES)),
        s: TenantSession = Depends(get_tenant_db),
    ) -> SessionOut:
        """Continue the session in another organization the person belongs to. The previous
        session's tokens are revoked and a new family is started."""
        memberships = list(
            s.scalars(select(Membership).where(Membership.user_id == principal.user_id))
        )
        chosen = next((m for m in memberships if m.org_id == body.org_id), None)
        if chosen is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to this organization")
        old = request.cookies.get(REFRESH_COOKIE)
        if old:
            row = s.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(old)))
            if row is not None and row.user_id == principal.user_id:
                _revoke_family(s, row.family_id)
        set_tenant(s, TenantContext(chosen.org_id, principal.user_id))
        user = s.get(User, principal.user_id)
        assert user is not None  # noqa: S101
        write_audit(
            s, request, "auth.switch_organization",
            principal=Principal(user.id, chosen.org_id, chosen.role, user.email, user.full_name),
            entity_type="organization", entity_id=chosen.org_id,
        )  # fmt: skip
        refresh = _issue_refresh(s, settings, user.id, chosen.org_id, uuid.uuid4())
        s.commit()
        _set_cookies(
            response, settings, _access(settings, user.id, chosen.org_id, chosen.role), refresh
        )
        return SessionOut(
            user=UserOut(id=user.id, email=user.email, full_name=user.full_name),
            org_id=chosen.org_id, role=chosen.role,
            memberships=[MembershipOut(org_id=m.org_id, role=m.role) for m in memberships],
        )  # fmt: skip

    return router
