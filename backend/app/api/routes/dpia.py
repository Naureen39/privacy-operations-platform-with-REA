import uuid
from datetime import UTC, date, datetime
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select

from app.api.deps import ALL_ROLES, Principal, app_settings, require_role, write_audit
from app.api.routes.fusion import make_loader
from app.api.routes.records import load_activity, visible_activities
from app.api.schemas import (
    CriterionOut,
    DpiaCreate,
    DpiaOut,
    DpiaPatch,
    DpiaSummaryOut,
    RiskIn,
    RiskOut,
    RiskPatch,
    ScaleIn,
    ScreeningOut,
)
from app.api.tenancy import get_tenant_db
from app.classify.embedder import Embedder
from app.classify.knowledge import Knowledge
from app.core.config import Settings
from app.db.enums import DpiaStatus, FindingStatus, Role
from app.db.models import (
    Dpia,
    DpiaRisk,
    DpiaScreening,
    Finding,
    ProcessingActivity,
    RegulationChunk,
)
from app.db.session import TenantSession
from app.dpia import matrix
from app.dpia.draft import Drafter
from app.dpia.export import to_pdf
from app.dpia.screening import CriteriaSet, Scale, load_criteria
from app.dpia.service import (
    AssessmentService,
    DpiaWorkflowError,
    RiskInput,
    ScreeningService,
    find_screening,
)
from app.knowledge.retrieval import HybridRetriever
from app.llm.budget import JobBudget
from app.llm.router import LLMRouter
from app.llm.tasks import Scope
from app.records.service import ActivityService
from app.workflow.notify import approval_event

router = APIRouter(prefix="/api/v1", tags=["impact-assessments"])

EDITORS = (Role.ADMIN, Role.ANALYST)


@lru_cache
def criteria_set() -> CriteriaSet:
    return load_criteria()


def _labels(request: Request) -> dict[str, str]:
    knowledge: Knowledge = request.app.state.knowledge
    return {c.id: c.label for c in knowledge.categories.values()}


def _workflow(error: DpiaWorkflowError) -> HTTPException:
    detail: dict[str, Any] = {"message": str(error)}
    if error.missing:
        detail["missing_fields"] = error.missing
    return HTTPException(status.HTTP_409_CONFLICT, detail)


# -- screening ---------------------------------------------------------------------------------


def _screening_out(row: DpiaScreening, activity: ProcessingActivity) -> ScreeningOut:
    return ScreeningOut(
        activity_id=activity.id,
        activity_name=activity.name,
        criteria=[CriterionOut(**c) for c in row.criteria],
        criteria_met=row.criteria_met,
        criteria_unknown=row.criteria_unknown,
        threshold=row.threshold,
        required=row.required,
        undecided=not row.required and row.criteria_met + row.criteria_unknown >= row.threshold,
        inputs=row.inputs,
        criteria_version=row.criteria_version,
        screened_at=row.updated_at,
    )


@router.post("/activities/{activity_id}/dpia-screening", response_model=ScreeningOut)
def run_screening(
    request: Request,
    activity_id: uuid.UUID,
    body: ScaleIn | None = None,
    principal: Principal = Depends(require_role(*EDITORS)),
    db: TenantSession = Depends(get_tenant_db),
    settings: Settings = Depends(app_settings),
) -> ScreeningOut:
    """Score the activity against the impact assessment criteria. The scale (people, countries) and
    criteria an analyst knows to apply can be stated; they are kept for the next screening."""
    activity = load_activity(db, principal, activity_id)
    row = _screen(request, db, principal, settings, activity, body)
    write_audit(
        db, request, "dpia.screening", principal=principal, entity_type="processing_activity",
        entity_id=activity.id,
        details={"met": row.criteria_met, "unknown": row.criteria_unknown, "required": row.required},
    )  # fmt: skip
    db.commit()
    return _screening_out(row, activity)


def _screen(
    request: Request, db: TenantSession, principal: Principal, settings: Settings,
    activity: ProcessingActivity, body: ScaleIn | None,
) -> DpiaScreening:  # fmt: skip
    systems = AssessmentService(db).systems_of(activity.id)
    if not systems:
        raise HTTPException(status.HTTP_409_CONFLICT, "The record is not linked to a system")
    scale = Scale(body.data_subjects_estimate, body.countries, list(body.flags)) if body else None
    service = ScreeningService(db, make_loader(request, db, principal, settings), criteria_set())
    return service.run(systems[0], activity, scale, principal.user_id)


@router.get("/activities/{activity_id}/dpia-screening", response_model=ScreeningOut)
def get_screening(
    activity_id: uuid.UUID,
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
) -> ScreeningOut:
    activity = load_activity(db, principal, activity_id)
    row = find_screening(db, activity.id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This activity has not been screened yet")
    return _screening_out(row, activity)


@router.get("/dpia-screenings", response_model=list[ScreeningOut])
def list_screenings(
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
) -> list[ScreeningOut]:
    visible = visible_activities(principal).subquery()
    stmt = (
        select(DpiaScreening, ProcessingActivity)
        .join(ProcessingActivity, ProcessingActivity.id == DpiaScreening.activity_id)
        .where(ProcessingActivity.id.in_(select(visible.c.id)))
        .order_by(ProcessingActivity.name)
    )
    return [_screening_out(s, a) for s, a in db.execute(stmt)]


# -- the assessment ----------------------------------------------------------------------------


def _risk_out(r: DpiaRisk) -> RiskOut:
    residual = (
        matrix.level(r.residual_likelihood, r.residual_severity)
        if r.residual_likelihood and r.residual_severity
        else None
    )
    return RiskOut(
        id=r.id, title=r.title, description=r.description, likelihood=r.likelihood,
        severity=r.severity, inherent_level=matrix.level(r.likelihood, r.severity),
        mitigation=r.mitigation, residual_likelihood=r.residual_likelihood,
        residual_severity=r.residual_severity, residual_level=residual, citation=r.citation,
    )  # fmt: skip


def _dpia_out(db: TenantSession, dpia: Dpia) -> DpiaOut:
    service = AssessmentService(db)
    activity = db.get(ProcessingActivity, dpia.activity_id)
    risks = service.risks(dpia.id)
    return DpiaOut(
        id=dpia.id,
        activity_id=dpia.activity_id,
        activity_name=activity.name if activity else "",
        status=dpia.status.value,
        criteria_met=dpia.criteria_met,
        description=dpia.description,
        necessity_proportionality=dpia.necessity_proportionality,
        residual_risk=dpia.residual_risk,
        officer_opinion=dpia.officer_opinion,
        risks=[_risk_out(r) for r in risks],
        matrix={
            "inherent": matrix.grid((r.likelihood, r.severity) for r in risks),
            "residual": matrix.grid((r.residual_likelihood, r.residual_severity) for r in risks if r.residual_likelihood and r.residual_severity),
        },
        missing_fields=service.missing(dpia),
        drafting=dpia.trigger_scores.get("drafting", {}),
        screening=dpia.trigger_scores.get("screening", {}),
        created_at=dpia.created_at,
    )  # fmt: skip


def _load_dpia(db: TenantSession, principal: Principal, dpia_id: uuid.UUID) -> Dpia:
    dpia = db.get(Dpia, dpia_id)
    if dpia is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assessment not found")
    load_activity(db, principal, dpia.activity_id)  # hides it from owners of other systems
    return dpia


@router.post(
    "/activities/{activity_id}/dpia", response_model=DpiaOut, status_code=status.HTTP_201_CREATED
)
def create_assessment(
    request: Request,
    activity_id: uuid.UUID,
    body: DpiaCreate,
    principal: Principal = Depends(require_role(*EDITORS)),
    db: TenantSession = Depends(get_tenant_db),
    settings: Settings = Depends(app_settings),
) -> DpiaOut:
    """Start an assessment for an activity that screening marks as likely to need one (or give a
    reason to start one anyway) and draft it: two assistant calls with retrieved regulation text,
    the risk catalogue as the fallback. Every risk cites an article or evidence."""
    activity = load_activity(db, principal, activity_id)
    if not db.scalar(select(func.count()).select_from(RegulationChunk).limit(1)):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The knowledge base is empty (run scripts/ingest_regulation.py)",
        )
    screening = find_screening(db, activity.id)
    if screening is None:
        screening = _screen(request, db, principal, settings, activity, None)
    service = AssessmentService(db)
    try:
        dpia = service.create(activity, screening, principal.user_id, body.reason)
    except DpiaWorkflowError as exc:
        raise _workflow(exc) from exc
    db.commit()  # the call log refers to the assessment, so it must exist before the model is asked

    systems = service.systems_of(activity.id)
    system_ids = [s.id for s in systems]
    findings = list(
        db.scalars(
            select(Finding).where(
                Finding.system_id.in_(system_ids),
                Finding.status.in_([FindingStatus.OPEN, FindingStatus.ACKNOWLEDGED]),
            )
        )
    )
    versions = ActivityService(db).version(activity.id, activity.current_version)
    special = list((versions.snapshot.get("special_categories") if versions else None) or [])
    met = [(c["id"], c["label"]) for c in screening.criteria if c["met"]]
    embedder: Embedder = request.app.state.embedder
    llm: LLMRouter = request.app.state.llm_router
    drafter = Drafter(db, HybridRetriever(db, embedder), llm, _labels(request))
    scope = Scope(
        principal.org_id, principal.user_id, system_ids[0] if system_ids else None, dpia.id,
        JobBudget(settings.llm_assessment_token_budget),
    )  # fmt: skip
    draft = drafter.draft(activity, met, special, findings, scope)
    service.set_texts(dpia, draft.description, draft.necessity)
    service.replace_risks(dpia, draft.risks)
    dpia.trigger_scores = {
        **dpia.trigger_scores,
        "drafting": {
            "sources": draft.sources, "tokens": draft.tokens, "calls": draft.calls,
            "notes": draft.notes, "drafted_at": datetime.now(UTC).isoformat(),
        },
    }  # fmt: skip
    write_audit(
        db, request, "dpia.create", principal=principal, entity_type="dpia", entity_id=dpia.id,
        details={"activity": str(activity.id), "tokens": draft.tokens, "sources": draft.sources, "risks": len(draft.risks)},
    )  # fmt: skip
    db.commit()
    return _dpia_out(db, dpia)


@router.get("/dpias", response_model=list[DpiaSummaryOut])
def list_assessments(
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
) -> list[DpiaSummaryOut]:
    visible = visible_activities(principal).subquery()
    stmt = (
        select(Dpia, ProcessingActivity)
        .join(ProcessingActivity, ProcessingActivity.id == Dpia.activity_id)
        .where(ProcessingActivity.id.in_(select(visible.c.id)))
        .order_by(Dpia.created_at.desc())
    )
    service = AssessmentService(db)
    return [
        DpiaSummaryOut(
            id=d.id, activity_id=a.id, activity_name=a.name, status=d.status.value,
            criteria_met=d.criteria_met, residual_risk=d.residual_risk,
            risks=len(service.risks(d.id)), created_at=d.created_at,
        )
        for d, a in db.execute(stmt)
    ]  # fmt: skip


@router.get("/dpias/{dpia_id}", response_model=DpiaOut)
def get_assessment(
    dpia_id: uuid.UUID,
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
) -> DpiaOut:
    return _dpia_out(db, _load_dpia(db, principal, dpia_id))


@router.patch("/dpias/{dpia_id}", response_model=DpiaOut)
def edit_assessment(
    request: Request,
    dpia_id: uuid.UUID,
    body: DpiaPatch,
    principal: Principal = Depends(require_role(*EDITORS)),
    db: TenantSession = Depends(get_tenant_db),
) -> DpiaOut:
    """Edit the description and the necessity text. Only the privacy officer (admin) records the opinion."""
    dpia = _load_dpia(db, principal, dpia_id)
    changes = body.model_dump(exclude_unset=True)
    if "officer_opinion" in changes and principal.role is not Role.ADMIN:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the privacy officer can record the opinion"
        )
    service = AssessmentService(db)
    try:
        if dpia.status in (DpiaStatus.DRAFT, DpiaStatus.REJECTED) or set(changes) <= {
            "officer_opinion"
        }:
            if "description" in changes or "necessity_proportionality" in changes:
                service.set_texts(
                    dpia, changes.get("description"), changes.get("necessity_proportionality")
                )
            if "officer_opinion" in changes:
                if dpia.status is DpiaStatus.APPROVED:
                    raise DpiaWorkflowError("An approved assessment cannot be edited")
                dpia.officer_opinion = changes["officer_opinion"]
        else:
            raise DpiaWorkflowError(
                f"A {dpia.status.value.replace('_', ' ')} assessment cannot be edited"
            )
    except DpiaWorkflowError as exc:
        raise _workflow(exc) from exc
    write_audit(
        db,
        request,
        "dpia.edit",
        principal=principal,
        entity_type="dpia",
        entity_id=dpia.id,
        details={"fields": sorted(changes)},
    )
    db.commit()
    return _dpia_out(db, dpia)


@router.post("/dpias/{dpia_id}/risks", response_model=DpiaOut, status_code=status.HTTP_201_CREATED)
def add_risk(
    request: Request,
    dpia_id: uuid.UUID,
    body: RiskIn,
    principal: Principal = Depends(require_role(*EDITORS)),
    db: TenantSession = Depends(get_tenant_db),
) -> DpiaOut:
    dpia = _load_dpia(db, principal, dpia_id)
    try:
        AssessmentService(db).add_risk(dpia, RiskInput(**body.model_dump()))
    except DpiaWorkflowError as exc:
        raise _workflow(exc) from exc
    write_audit(
        db, request, "dpia.risk_add", principal=principal, entity_type="dpia", entity_id=dpia.id
    )
    db.commit()
    return _dpia_out(db, dpia)


def _risk(db: TenantSession, dpia: Dpia, risk_id: uuid.UUID) -> DpiaRisk:
    risk = db.get(DpiaRisk, risk_id)
    if risk is None or risk.dpia_id != dpia.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Risk not found")
    return risk


@router.patch("/dpias/{dpia_id}/risks/{risk_id}", response_model=DpiaOut)
def edit_risk(
    request: Request,
    dpia_id: uuid.UUID,
    risk_id: uuid.UUID,
    body: RiskPatch,
    principal: Principal = Depends(require_role(*EDITORS)),
    db: TenantSession = Depends(get_tenant_db),
) -> DpiaOut:
    dpia = _load_dpia(db, principal, dpia_id)
    try:
        AssessmentService(db).update_risk(
            dpia, _risk(db, dpia, risk_id), body.model_dump(exclude_unset=True)
        )
    except DpiaWorkflowError as exc:
        raise _workflow(exc) from exc
    write_audit(
        db, request, "dpia.risk_edit", principal=principal, entity_type="dpia", entity_id=dpia.id
    )
    db.commit()
    return _dpia_out(db, dpia)


@router.delete("/dpias/{dpia_id}/risks/{risk_id}", response_model=DpiaOut)
def delete_risk(
    request: Request,
    dpia_id: uuid.UUID,
    risk_id: uuid.UUID,
    principal: Principal = Depends(require_role(*EDITORS)),
    db: TenantSession = Depends(get_tenant_db),
) -> DpiaOut:
    dpia = _load_dpia(db, principal, dpia_id)
    try:
        AssessmentService(db).delete_risk(dpia, _risk(db, dpia, risk_id))
    except DpiaWorkflowError as exc:
        raise _workflow(exc) from exc
    write_audit(
        db, request, "dpia.risk_delete", principal=principal, entity_type="dpia", entity_id=dpia.id
    )
    db.commit()
    return _dpia_out(db, dpia)


def _transition(
    request: Request,
    db: TenantSession,
    principal: Principal,
    dpia_id: uuid.UUID,
    action: str,
    note: str | None = None,
) -> DpiaOut:
    dpia = _load_dpia(db, principal, dpia_id)
    service = AssessmentService(db)
    try:
        if action == "submit":
            service.submit(dpia, principal.user_id)
        else:
            service.decide(dpia, principal.user_id, action == "approve", note)
    except DpiaWorkflowError as exc:
        raise _workflow(exc) from exc
    approval_event(db, "dpia", dpia.id, "Impact assessment", action, principal.user_id)
    write_audit(
        db,
        request,
        f"dpia.{action}",
        principal=principal,
        entity_type="dpia",
        entity_id=dpia.id,
        details={"note": note},
    )
    db.commit()
    return _dpia_out(db, dpia)


@router.post("/dpias/{dpia_id}/submit", response_model=DpiaOut)
def submit_assessment(
    request: Request,
    dpia_id: uuid.UUID,
    principal: Principal = Depends(require_role(*EDITORS)),
    db: TenantSession = Depends(get_tenant_db),
) -> DpiaOut:
    """Send a complete assessment to the privacy officer."""
    return _transition(request, db, principal, dpia_id, "submit")


@router.post("/dpias/{dpia_id}/approve", response_model=DpiaOut)
def approve_assessment(
    request: Request,
    dpia_id: uuid.UUID,
    body: DpiaCreate,
    principal: Principal = Depends(require_role(Role.ADMIN)),
    db: TenantSession = Depends(get_tenant_db),
) -> DpiaOut:
    return _transition(request, db, principal, dpia_id, "approve", body.reason)


@router.post("/dpias/{dpia_id}/reject", response_model=DpiaOut)
def reject_assessment(
    request: Request,
    dpia_id: uuid.UUID,
    body: DpiaCreate,
    principal: Principal = Depends(require_role(Role.ADMIN)),
    db: TenantSession = Depends(get_tenant_db),
) -> DpiaOut:
    return _transition(request, db, principal, dpia_id, "reject", body.reason)


@router.get("/dpias/{dpia_id}/export.pdf")
def export_assessment(
    request: Request,
    dpia_id: uuid.UUID,
    principal: Principal = Depends(require_role(Role.ADMIN, Role.ANALYST, Role.VIEWER)),
    db: TenantSession = Depends(get_tenant_db),
) -> Response:
    dpia = _load_dpia(db, principal, dpia_id)
    content = to_pdf(_dpia_out(db, dpia).model_dump(mode="json"), date.today())
    write_audit(
        db, request, "export.dpia", principal=principal, entity_type="dpia", entity_id=dpia.id
    )
    db.commit()
    return Response(
        content,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="impact-assessment.pdf"'},
    )
