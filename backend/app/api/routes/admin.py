from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select

from app.api.deps import Principal, app_settings, require_role, write_audit
from app.api.schemas import AuditEntryOut, OrgSettings
from app.api.tenancy import get_tenant_db
from app.core.config import Settings
from app.db.enums import Role
from app.db.models import AuditLog, Organization
from app.db.session import TenantSession

router = APIRouter(prefix="/api/v1", tags=["admin"])


def _load(
    db: TenantSession, org_id: object, defaults: Settings
) -> tuple[Organization, OrgSettings]:
    org = db.get(Organization, org_id)
    assert org is not None  # noqa: S101  (the principal's organization always exists)
    base = {"evidence_retention_days": defaults.evidence_retention_days}
    return org, OrgSettings.model_validate({**base, **org.settings})


@router.get("/settings", response_model=OrgSettings)
def get_org_settings(
    principal: Principal = Depends(require_role(Role.ADMIN)),
    db: TenantSession = Depends(get_tenant_db),
    defaults: Settings = Depends(app_settings),
) -> OrgSettings:
    return _load(db, principal.org_id, defaults)[1]


@router.put("/settings", response_model=OrgSettings)
def update_org_settings(
    request: Request,
    body: OrgSettings,
    principal: Principal = Depends(require_role(Role.ADMIN)),
    db: TenantSession = Depends(get_tenant_db),
    defaults: Settings = Depends(app_settings),
) -> OrgSettings:
    org, current = _load(db, principal.org_id, defaults)
    changed = sorted(
        key for key, value in body.model_dump().items() if value != current.model_dump()[key]
    )
    org.settings = body.model_dump()
    write_audit(db, request, "settings.update", principal=principal,
                entity_type="organization", entity_id=org.id, details={"changed": changed})  # fmt: skip
    db.commit()
    return body


@router.get("/audit-log", response_model=list[AuditEntryOut])
def list_audit_log(
    action: str | None = Query(None, max_length=80),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(require_role(Role.ADMIN, Role.VIEWER)),
    db: TenantSession = Depends(get_tenant_db),
) -> list[AuditLog]:
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    return list(db.scalars(stmt))
