import dataclasses
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import Select, select

from app.api.deps import (
    ALL_ROLES,
    Principal,
    app_settings,
    get_visible_system,
    require_role,
    write_audit,
)
from app.api.pagination import Page, paged
from app.api.schemas import FindingOut, FindingPatch, FusionSummaryOut
from app.api.tenancy import get_tenant_db
from app.core.config import Settings
from app.db.enums import FindingStatus, JobState, Role
from app.db.models import Finding, System, TaxonomyEntry
from app.db.session import TenantSession
from app.fusion.loader import FactsLoader
from app.fusion.service import FusionService
from app.services import pipeline

router = APIRouter(prefix="/api/v1", tags=["fusion"])

REVIEWERS = (Role.ADMIN, Role.ANALYST)
READY_STATES = (
    JobState.CLASSIFIED,
    JobState.FUSED,
    JobState.DRAFTED,
    JobState.AWAITING_REVIEW,
    JobState.APPROVED,
    JobState.PUBLISHED,
)


def make_loader(
    request: Request, db: TenantSession, principal: Principal, settings: Settings
) -> FactsLoader:
    """The facts loader for a request (kept for the routes that build one per call)."""
    return pipeline.make_loader(request.app.state, db, principal.org_id)


@router.post("/systems/{system_id}/fusion", response_model=FusionSummaryOut)
def run_fusion(
    request: Request,
    system_id: uuid.UUID,
    principal: Principal = Depends(require_role(*REVIEWERS)),
    db: TenantSession = Depends(get_tenant_db),
    settings: Settings = Depends(app_settings),
) -> FusionSummaryOut:
    """Compare the questionnaire, the notice and the evidence and raise findings."""
    system = get_visible_system(db, principal, system_id)
    if system.status not in READY_STATES:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Run discovery and classification before the comparison"
        )
    if not db.scalar(select(TaxonomyEntry.id).limit(1)):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The taxonomy index is not loaded (run scripts/load_taxonomy.py)",
        )
    llm = request.app.state.llm_router
    loader = make_loader(request, db, principal, settings)
    summary = FusionService(
        db, loader, llm if llm.providers else None, principal.org_id, principal.user_id
    ).run(system)
    write_audit(
        db, request, "fusion.run", principal=principal, entity_type="system",
        entity_id=system.id,
        details={"findings_open": summary.findings_open, "adjudicated": summary.adjudicated, "tokens": summary.tokens_used},
    )  # fmt: skip
    db.commit()
    return FusionSummaryOut(**dataclasses.asdict(summary))


def _visible_findings(principal: Principal) -> Select[Finding]:
    stmt = select(Finding)
    if principal.role is Role.SYSTEM_OWNER:
        owned = select(System.id).where(System.owner_user_id == principal.user_id)
        stmt = stmt.where(Finding.system_id.in_(owned))
    return stmt


@router.get("/findings", response_model=list[FindingOut])
def list_findings(
    response: Response,
    system_id: uuid.UUID | None = None,
    type: str | None = Query(None, max_length=80),
    severity: str | None = Query(None, max_length=20),
    status_filter: str | None = Query(None, alias="status", max_length=20),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
) -> list[Finding]:
    stmt = _visible_findings(principal)
    if system_id is not None:
        get_visible_system(db, principal, system_id)
        stmt = stmt.where(Finding.system_id == system_id)
    if type:
        stmt = stmt.where(Finding.type == type)
    if severity:
        stmt = stmt.where(Finding.severity == severity)
    if status_filter:
        stmt = stmt.where(Finding.status == status_filter)
    stmt = stmt.order_by(Finding.created_at.desc(), Finding.id)
    return paged(db, stmt, Page(limit, offset), response)


@router.patch("/findings/{finding_id}", response_model=FindingOut)
def update_finding(
    request: Request,
    finding_id: uuid.UUID,
    body: FindingPatch,
    principal: Principal = Depends(require_role(*REVIEWERS)),
    db: TenantSession = Depends(get_tenant_db),
) -> Finding:
    """Acknowledge, dismiss or resolve a finding. A dismissed finding stays dismissed when the
    comparison runs again; it is only closed automatically when the problem disappears."""
    finding = db.scalars(_visible_findings(principal).where(Finding.id == finding_id)).first()
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")
    before = finding.status.value
    finding.status = FindingStatus(body.status)
    finding.resolved_at = datetime.now(UTC) if body.status == "resolved" else None
    write_audit(
        db, request, "finding.update", principal=principal, entity_type="finding",
        entity_id=finding.id, details={"from": before, "to": body.status},
    )  # fmt: skip
    db.commit()
    return finding
