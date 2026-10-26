import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select

from app.api.deps import (
    ALL_ROLES,
    Principal,
    get_visible_system,
    require_role,
    write_audit,
)
from app.api.pagination import Page, paged
from app.api.schemas import SystemCreate, SystemOut, SystemUpdate, slugify
from app.api.tenancy import get_tenant_db
from app.db.enums import Role
from app.db.models import Membership, System
from app.db.session import TenantSession

router = APIRouter(prefix="/api/v1/systems", tags=["systems"])

WRITERS = (Role.ADMIN, Role.ANALYST)


def _check_owner(db: TenantSession, principal: Principal, owner_id: uuid.UUID | None) -> None:
    if owner_id is None:
        return
    member = db.scalar(
        select(Membership).where(
            Membership.user_id == owner_id, Membership.org_id == principal.org_id
        )
    )
    if member is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Owner is not in this organization"
        )


@router.get("", response_model=list[SystemOut])
def list_systems(
    response: Response,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
) -> list[System]:
    stmt = select(System).order_by(System.name)
    if principal.role is Role.SYSTEM_OWNER:
        stmt = stmt.where(System.owner_user_id == principal.user_id)
    return paged(db, stmt, Page(limit, offset), response)


@router.post("", response_model=SystemOut, status_code=status.HTTP_201_CREATED)
def create_system(
    request: Request,
    body: SystemCreate,
    principal: Principal = Depends(require_role(*WRITERS)),
    db: TenantSession = Depends(get_tenant_db),
) -> System:
    _check_owner(db, principal, body.owner_user_id)
    slug = slugify(body.name)
    if db.scalar(select(System.id).where(System.slug == slug)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A system with this name already exists")
    system = System(
        name=body.name,
        slug=slug,
        description=body.description,
        owner_user_id=body.owner_user_id,
    )
    db.add(system)
    db.flush()
    write_audit(db, request, "system.create", principal=principal, entity_type="system",
                entity_id=system.id)  # fmt: skip
    db.commit()
    return system


@router.get("/{system_id}", response_model=SystemOut)
def get_system(
    system_id: uuid.UUID,
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
) -> System:
    return get_visible_system(db, principal, system_id)


@router.patch("/{system_id}", response_model=SystemOut)
def update_system(
    request: Request,
    system_id: uuid.UUID,
    body: SystemUpdate,
    principal: Principal = Depends(require_role(*WRITERS)),
    db: TenantSession = Depends(get_tenant_db),
) -> System:
    system = get_visible_system(db, principal, system_id)
    changes = body.model_dump(exclude_unset=True)
    if "owner_user_id" in changes:
        _check_owner(db, principal, changes["owner_user_id"])
    for field, value in changes.items():
        if field == "name" and value is None:
            continue
        setattr(system, field, value)
    write_audit(db, request, "system.update", principal=principal, entity_type="system",
                entity_id=system.id, details={"fields": sorted(changes)})  # fmt: skip
    db.commit()
    return system


@router.delete("/{system_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_system(
    request: Request,
    system_id: uuid.UUID,
    principal: Principal = Depends(require_role(Role.ADMIN)),
    db: TenantSession = Depends(get_tenant_db),
) -> Response:
    system = get_visible_system(db, principal, system_id)
    db.delete(system)
    write_audit(db, request, "system.delete", principal=principal, entity_type="system",
                entity_id=system_id)  # fmt: skip
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
