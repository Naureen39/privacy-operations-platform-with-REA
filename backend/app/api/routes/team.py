import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select

from app.api.deps import Principal, require_role, write_audit
from app.api.pagination import Page, page_params
from app.api.schemas_console import TeamMemberOut, TeamRoleIn
from app.api.tenancy import get_tenant_db
from app.db.enums import Role
from app.db.models import Membership, User
from app.db.session import TenantSession

router = APIRouter(prefix="/api/v1/team", tags=["team"])


def _out(member: Membership, user: User, you: uuid.UUID) -> TeamMemberOut:
    return TeamMemberOut(
        user_id=user.id, email=user.email, full_name=user.full_name, role=member.role,
        is_active=user.is_active, last_login_at=user.last_login_at, is_you=user.id == you,
    )  # fmt: skip


def _member(db: TenantSession, user_id: uuid.UUID) -> tuple[Membership, User]:
    row = db.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.user_id == user_id)
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    return row[0], row[1]


def _admins(db: TenantSession) -> int:
    return int(
        db.scalar(select(func.count()).select_from(Membership).where(Membership.role == Role.ADMIN))
        or 0
    )


@router.get("", response_model=list[TeamMemberOut])
def list_members(
    response: Response,
    page: Page = Depends(page_params),
    principal: Principal = Depends(require_role(Role.ADMIN)),
    db: TenantSession = Depends(get_tenant_db),
) -> list[TeamMemberOut]:
    """The people with access to this organization and their roles."""
    query = (
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .order_by(User.full_name, User.email)
    )
    total = db.scalar(select(func.count()).select_from(Membership)) or 0
    response.headers["X-Total-Count"] = str(total)
    rows = db.execute(query.limit(page.limit).offset(page.offset)).all()
    return [_out(m, u, principal.user_id) for m, u in rows]


@router.patch("/{user_id}", response_model=TeamMemberOut)
def change_role(
    request: Request,
    user_id: uuid.UUID,
    body: TeamRoleIn,
    principal: Principal = Depends(require_role(Role.ADMIN)),
    db: TenantSession = Depends(get_tenant_db),
) -> TeamMemberOut:
    """Change a member's role. You cannot change your own, so an organization is never left
    without an administrator by accident."""
    if user_id == principal.user_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot change your own role")
    member, user = _member(db, user_id)
    before = member.role
    member.role = body.role
    write_audit(
        db, request, "team.role_changed", principal=principal, entity_type="user", entity_id=user.id,
        details={"from": before.value, "to": body.role.value},
    )  # fmt: skip
    db.commit()
    return _out(member, user, principal.user_id)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    request: Request,
    user_id: uuid.UUID,
    principal: Principal = Depends(require_role(Role.ADMIN)),
    db: TenantSession = Depends(get_tenant_db),
) -> None:
    """Remove a person's access to this organization (their account is not deleted)."""
    if user_id == principal.user_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot remove yourself")
    member, user = _member(db, user_id)
    if member.role is Role.ADMIN and _admins(db) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "The last administrator cannot be removed")
    db.delete(member)
    write_audit(
        db, request, "team.member_removed", principal=principal, entity_type="user",
        entity_id=user.id,
    )  # fmt: skip
    db.commit()
