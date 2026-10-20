import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select

from app.api.deps import (
    ALL_ROLES,
    Principal,
    get_visible_system,
    require_role,
    write_audit,
)
from app.api.schemas import (
    DataElementOut,
    DiscoveryEvidenceOut,
    DiscoveryRunOut,
    RecipientOut,
    TechnologyOut,
)
from app.api.tenancy import get_tenant_db
from app.db.enums import Role
from app.db.models import DataElement, DiscoveryEvidence, DiscoveryRun, Recipient, Technology
from app.db.session import TenantSession
from app.discovery.executor import Executor
from app.discovery.service import DiscoveryService
from app.services.evidence_store import EvidenceStore

router = APIRouter(prefix="/api/v1", tags=["discovery"])

RUNNERS = (Role.ADMIN, Role.ANALYST)


def get_executor(request: Request) -> Executor:
    executor: Executor = request.app.state.discovery_executor
    return executor


def get_store(request: Request) -> EvidenceStore:
    store: EvidenceStore = request.app.state.evidence_store
    return store


@router.post(
    "/systems/{system_id}/discovery-runs",
    response_model=DiscoveryRunOut,
    status_code=status.HTTP_201_CREATED,
)
def start_discovery(
    request: Request,
    system_id: uuid.UUID,
    principal: Principal = Depends(require_role(*RUNNERS)),
    db: TenantSession = Depends(get_tenant_db),
    executor: Executor = Depends(get_executor),
    store: EvidenceStore = Depends(get_store),
) -> DiscoveryRun:
    """Run discovery now and return the finished run (Phase 11 moves this to a background job)."""
    system = get_visible_system(db, principal, system_id)
    run = DiscoveryService(db, store, executor).run(system, principal.user_id)
    summary = run.summary or {}
    write_audit(
        db,
        request,
        "discovery.run",
        principal=principal,
        entity_type="system",
        entity_id=system.id,
        details={
            "run_id": str(run.id),
            "state": run.state.value,
            "data_elements": summary.get("data_elements", 0),
            "recipients": summary.get("recipients", 0),
            "extractor_mix": summary.get("extractor_mix", {}),
        },
    )
    db.commit()
    return run


@router.get("/systems/{system_id}/discovery-runs", response_model=list[DiscoveryRunOut])
def list_runs(
    system_id: uuid.UUID,
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
) -> list[DiscoveryRun]:
    get_visible_system(db, principal, system_id)
    stmt = (
        select(DiscoveryRun)
        .where(DiscoveryRun.system_id == system_id)
        .order_by(DiscoveryRun.started_at.desc())
        .limit(50)
    )
    return list(db.scalars(stmt))


@router.get("/systems/{system_id}/data-elements", response_model=list[DataElementOut])
def list_data_elements(
    system_id: uuid.UUID,
    source_kind: str | None = Query(None, max_length=40),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
) -> list[DataElement]:
    get_visible_system(db, principal, system_id)
    stmt = (
        select(DataElement)
        .where(DataElement.system_id == system_id)
        .order_by(DataElement.name, DataElement.path)
    )
    if source_kind:
        stmt = stmt.where(DataElement.source_kind == source_kind)
    return list(db.scalars(stmt.limit(limit).offset(offset)))


@router.get("/systems/{system_id}/recipients", response_model=list[RecipientOut])
def list_recipients(
    system_id: uuid.UUID,
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
) -> list[Recipient]:
    get_visible_system(db, principal, system_id)
    stmt = select(Recipient).where(Recipient.system_id == system_id).order_by(Recipient.domain)
    return list(db.scalars(stmt))


@router.get("/systems/{system_id}/technologies", response_model=list[TechnologyOut])
def list_technologies(
    system_id: uuid.UUID,
    kind: str | None = Query(None, max_length=80),
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
) -> list[Technology]:
    get_visible_system(db, principal, system_id)
    stmt = (
        select(Technology)
        .where(Technology.system_id == system_id)
        .order_by(Technology.kind, Technology.name)
    )
    if kind:
        stmt = stmt.where(Technology.kind == kind)
    return list(db.scalars(stmt))


@router.get("/discovery-evidence/{evidence_id}", response_model=DiscoveryEvidenceOut)
def get_discovery_evidence(
    request: Request,
    evidence_id: uuid.UUID,
    principal: Principal = Depends(require_role(*RUNNERS)),
    db: TenantSession = Depends(get_tenant_db),
) -> DiscoveryEvidence:
    """The stored extractor output behind a fact (sample values are masked)."""
    row = db.get(DiscoveryEvidence, evidence_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Discovery evidence not found")
    write_audit(
        db,
        request,
        "discovery.evidence_view",
        principal=principal,
        entity_type="discovery_evidence",
        entity_id=row.id,
    )
    db.commit()
    return row
