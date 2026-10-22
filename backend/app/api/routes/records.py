import uuid
from datetime import date
from typing import Any

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
from app.api.routes.fusion import READY_STATES, make_loader
from app.api.schemas import (
    ActivityGenerateOut,
    ActivityOut,
    ActivityPatch,
    DecisionIn,
    DiffOut,
    ReviewItemOut,
    VersionDetailOut,
    VersionOut,
)
from app.api.tenancy import get_tenant_db
from app.classify.knowledge import Knowledge
from app.core.config import Settings
from app.db.enums import ActivityStatus, FindingSeverity, FindingStatus, Role
from app.db.models import ActivitySystem, Finding, ProcessingActivity, System
from app.db.session import TenantSession
from app.llm.budget import JobBudget
from app.llm.errors import LLMError
from app.llm.router import LLMRouter
from app.llm.schemas import PurposeAndBasis
from app.llm.tasks import Scope, suggest_purpose_and_basis
from app.records.builder import build_draft, summary_text
from app.records.diff import diff_snapshots, summarize
from app.records.export import RegisterRow, to_pdf, to_xlsx
from app.records.service import ActivityService, WorkflowError

router = APIRouter(prefix="/api/v1", tags=["records"])

EDITORS = (Role.ADMIN, Role.ANALYST)
EXPORTERS = (Role.ADMIN, Role.ANALYST, Role.VIEWER)
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _labels(request: Request) -> dict[str, str]:
    knowledge: Knowledge = request.app.state.knowledge
    return {c.id: c.label for c in knowledge.categories.values()}


def _visible(principal: Principal) -> Select[ProcessingActivity]:
    stmt = select(ProcessingActivity)
    if principal.role is Role.SYSTEM_OWNER:
        owned = (
            select(ActivitySystem.activity_id)
            .join(System, System.id == ActivitySystem.system_id)
            .where(System.owner_user_id == principal.user_id)
        )
        stmt = stmt.where(ProcessingActivity.id.in_(owned))
    return stmt


def _load(db: TenantSession, principal: Principal, activity_id: uuid.UUID) -> ProcessingActivity:
    activity = db.scalars(_visible(principal).where(ProcessingActivity.id == activity_id)).first()
    if activity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Record not found")
    return activity


def _out(db: TenantSession, request: Request, activity: ProcessingActivity) -> ActivityOut:
    service = ActivityService(db)
    latest = service.version(activity.id, activity.current_version)
    special = list((latest.snapshot.get("special_categories") if latest else None) or [])
    system_ids = list(
        db.scalars(
            select(ActivitySystem.system_id).where(ActivitySystem.activity_id == activity.id)
        )
    )
    fields = {
        "name": activity.name,
        "data_categories": activity.data_categories,
        "data_subjects": activity.data_subjects,
        "recipients": activity.recipients,
        "retention": activity.retention,
    }
    return ActivityOut(
        id=activity.id,
        name=activity.name,
        status=activity.status.value,
        current_version=activity.current_version,
        system_ids=system_ids,
        owner_user_id=activity.owner_user_id,
        purposes=list(activity.purposes),
        data_subjects=list(activity.data_subjects),
        data_categories=list(activity.data_categories),
        recipients=list(activity.recipients),
        transfers=list(activity.transfers),
        retention=activity.retention,
        security_measures=activity.security_measures,
        lawful_basis=activity.lawful_basis,
        special_category_condition=activity.special_category_condition,
        next_review_date=activity.next_review_date,
        citations=activity.citations,
        special_categories=special,
        missing_fields=service.missing_fields(activity),
        summary=summary_text(fields, _labels(request), special),
    )


def _workflow(error: WorkflowError) -> HTTPException:
    detail: dict[str, Any] = {"message": str(error)}
    if error.missing:
        detail["missing_fields"] = error.missing
    return HTTPException(status.HTTP_409_CONFLICT, detail)


# -- generation --------------------------------------------------------------------------------


@router.post("/systems/{system_id}/record", response_model=ActivityGenerateOut)
def generate_record(
    request: Request,
    system_id: uuid.UUID,
    principal: Principal = Depends(require_role(*EDITORS)),
    db: TenantSession = Depends(get_tenant_db),
    settings: Settings = Depends(app_settings),
) -> ActivityGenerateOut:
    """Build or refresh the record of processing of a system from the evidence and the answers.
    Needs the comparison to have run. Purposes and a lawful basis are suggested by the assistant
    (one call, cached) and marked for review."""
    system = get_visible_system(db, principal, system_id)
    if system.status not in READY_STATES or system.status.value in ("CLASSIFIED",):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Run the comparison before generating the record"
        )
    loader = make_loader(request, db, principal, settings)
    facts = loader.load(system)

    suggestion: PurposeAndBasis | None = None
    tokens = 0
    llm: LLMRouter = request.app.state.llm_router
    if llm.providers:
        labels = _labels(request)
        special = sorted(
            {labels.get(e.category or "", e.name) for e in facts.elements if e.special}
        )
        try:
            suggestion, result = suggest_purpose_and_basis(
                llm,
                Scope(
                    principal.org_id,
                    principal.user_id,
                    system.id,
                    job=JobBudget(settings.llm_onboarding_token_budget),
                ),
                name=facts.name,
                description=system.description or "",
                data_categories=sorted(
                    {labels.get(e.category or "", "") for e in facts.elements if e.category} - {""}
                ),
                special_categories=special,
                data_subjects=facts.questionnaire.data_subjects if facts.questionnaire else [],
                recipients=[
                    {"vendor": r.label, "role": r.role, "country": r.country or "unknown"}
                    for r in facts.recipients
                    if not r.internal
                ],
                declared_purposes=(
                    [str(p) for p in (facts.questionnaire.answers.get("purposes") or [])]
                    if facts.questionnaire
                    else []
                ),
            )
            tokens = result.tokens
        except LLMError:
            suggestion = None  # the record is still built from the answers; a person can edit it

    draft = build_draft(
        facts,
        str(system.owner_user_id) if system.owner_user_id else None,
        _labels(request),
        suggestion,
    )
    result_ = ActivityService(db).generate(system, draft, principal.user_id)
    write_audit(
        db, request, "record.generate", principal=principal, entity_type="processing_activity",
        entity_id=result_.activity.id,
        details={"created": result_.created, "changed": result_.changed, "version": result_.version, "tokens": tokens},
    )  # fmt: skip
    db.commit()
    return ActivityGenerateOut(
        activity=_out(db, request, result_.activity),
        created=result_.created,
        changed=result_.changed,
        suggestion_used=suggestion is not None,
        tokens_used=tokens,
    )


# -- reading -----------------------------------------------------------------------------------


@router.get("/activities", response_model=list[ActivityOut])
def list_activities(
    request: Request,
    status_filter: ActivityStatus | None = Query(None, alias="status"),
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
) -> list[ActivityOut]:
    stmt = _visible(principal).order_by(ProcessingActivity.name)
    if status_filter:
        stmt = stmt.where(ProcessingActivity.status == status_filter)
    return [_out(db, request, a) for a in db.scalars(stmt.limit(500))]


@router.get("/activities/{activity_id}", response_model=ActivityOut)
def get_activity(
    request: Request,
    activity_id: uuid.UUID,
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
) -> ActivityOut:
    return _out(db, request, _load(db, principal, activity_id))


@router.get("/activities/{activity_id}/versions", response_model=list[VersionOut])
def list_versions(
    activity_id: uuid.UUID,
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
) -> list[Any]:
    _load(db, principal, activity_id)
    return ActivityService(db).versions(activity_id)


@router.get("/activities/{activity_id}/versions/{number}", response_model=VersionDetailOut)
def get_version(
    activity_id: uuid.UUID,
    number: int,
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
) -> Any:
    _load(db, principal, activity_id)
    version = ActivityService(db).version(activity_id, number)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found")
    return version


@router.get("/activities/{activity_id}/diff", response_model=DiffOut)
def diff_versions(
    activity_id: uuid.UUID,
    from_version: int = Query(alias="from", ge=1),
    to_version: int = Query(alias="to", ge=1),
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
) -> DiffOut:
    _load(db, principal, activity_id)
    service = ActivityService(db)
    a, b = service.version(activity_id, from_version), service.version(activity_id, to_version)
    if a is None or b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found")
    changes = diff_snapshots(a.snapshot, b.snapshot)
    return DiffOut(
        from_version=from_version,
        to_version=to_version,
        summary=summarize(changes),
        changes=changes,
    )


# -- editing and review ------------------------------------------------------------------------


@router.patch("/activities/{activity_id}", response_model=ActivityOut)
def edit_activity(
    request: Request,
    activity_id: uuid.UUID,
    body: ActivityPatch,
    principal: Principal = Depends(require_role(*EDITORS)),
    db: TenantSession = Depends(get_tenant_db),
) -> ActivityOut:
    """Edit fields of a record. Each edit is a new version and returns the record to draft."""
    activity = _load(db, principal, activity_id)
    changes = body.model_dump(exclude_unset=True)
    try:
        version = ActivityService(db).edit(activity, changes, principal.user_id)
    except WorkflowError as exc:
        raise _workflow(exc) from exc
    write_audit(
        db, request, "record.edit", principal=principal, entity_type="processing_activity",
        entity_id=activity.id, details={"fields": sorted(changes), "version": version},
    )  # fmt: skip
    db.commit()
    return _out(db, request, activity)


def _transition(
    request: Request,
    db: TenantSession,
    principal: Principal,
    activity_id: uuid.UUID,
    action: str,
    note: str | None = None,
) -> ActivityOut:
    activity = _load(db, principal, activity_id)
    service = ActivityService(db)
    try:
        if action == "submit":
            service.submit(activity, principal.user_id)
        elif action == "approve":
            service.decide(activity, principal.user_id, True, note)
        elif action == "reject":
            service.decide(activity, principal.user_id, False, note)
        else:
            service.publish(activity)
    except WorkflowError as exc:
        raise _workflow(exc) from exc
    write_audit(
        db, request, f"record.{action}", principal=principal, entity_type="processing_activity",
        entity_id=activity.id, details={"version": activity.current_version, "note": note},
    )  # fmt: skip
    db.commit()
    return _out(db, request, activity)


@router.post("/activities/{activity_id}/submit", response_model=ActivityOut)
def submit_activity(
    request: Request,
    activity_id: uuid.UUID,
    principal: Principal = Depends(require_role(*EDITORS)),
    db: TenantSession = Depends(get_tenant_db),
) -> ActivityOut:
    """Send a complete record to the privacy officer."""
    return _transition(request, db, principal, activity_id, "submit")


@router.post("/activities/{activity_id}/approve", response_model=ActivityOut)
def approve_activity(
    request: Request,
    activity_id: uuid.UUID,
    body: DecisionIn,
    principal: Principal = Depends(require_role(Role.ADMIN)),
    db: TenantSession = Depends(get_tenant_db),
) -> ActivityOut:
    return _transition(request, db, principal, activity_id, "approve", body.note)


@router.post("/activities/{activity_id}/reject", response_model=ActivityOut)
def reject_activity(
    request: Request,
    activity_id: uuid.UUID,
    body: DecisionIn,
    principal: Principal = Depends(require_role(Role.ADMIN)),
    db: TenantSession = Depends(get_tenant_db),
) -> ActivityOut:
    return _transition(request, db, principal, activity_id, "reject", body.note)


@router.post("/activities/{activity_id}/publish", response_model=ActivityOut)
def publish_activity(
    request: Request,
    activity_id: uuid.UUID,
    principal: Principal = Depends(require_role(Role.ADMIN)),
    db: TenantSession = Depends(get_tenant_db),
) -> ActivityOut:
    return _transition(request, db, principal, activity_id, "publish")


@router.get("/review-queue", response_model=list[ReviewItemOut])
def review_queue(
    principal: Principal = Depends(require_role(*EDITORS)),
    db: TenantSession = Depends(get_tenant_db),
) -> list[ReviewItemOut]:
    """What needs a person: records awaiting approval, incomplete drafts, serious open findings."""
    service = ActivityService(db)
    items: list[ReviewItemOut] = []
    for activity in db.scalars(select(ProcessingActivity).order_by(ProcessingActivity.updated_at)):
        if activity.status is ActivityStatus.AWAITING_REVIEW:
            items.append(
                ReviewItemOut(
                    kind="approval",
                    title=f"Approve: {activity.name}",
                    severity="medium",
                    activity_id=activity.id,
                    since=activity.updated_at,
                )
            )
        elif activity.status is ActivityStatus.DRAFT:
            missing = service.missing_fields(activity)
            if missing:
                items.append(
                    ReviewItemOut(
                        kind="incomplete",
                        title=f"Complete: {activity.name}",
                        severity="medium",
                        activity_id=activity.id,
                        since=activity.updated_at,
                        detail="Missing: " + ", ".join(missing),
                    )
                )
    serious = (FindingSeverity.CRITICAL, FindingSeverity.HIGH)
    for finding in db.scalars(
        select(Finding)
        .where(Finding.status == FindingStatus.OPEN, Finding.severity.in_(serious))
        .order_by(Finding.created_at)
    ):
        items.append(
            ReviewItemOut(
                kind="finding",
                title=finding.title,
                severity=finding.severity.value,
                finding_id=finding.id,
                system_id=finding.system_id,
                since=finding.created_at,
                detail=finding.type,
            )
        )
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return sorted(items, key=lambda i: order.get(i.severity, 4))


# -- exports -----------------------------------------------------------------------------------


def _register_rows(db: TenantSession, request: Request, principal: Principal) -> list[RegisterRow]:
    service = ActivityService(db)
    rows = []
    for activity in db.scalars(_visible(principal).order_by(ProcessingActivity.name)):
        latest = service.version(activity.id, activity.current_version)
        system_ids = list(
            db.scalars(
                select(ActivitySystem.system_id).where(ActivitySystem.activity_id == activity.id)
            )
        )
        names = [s.name for s in (db.get(System, i) for i in system_ids) if s is not None]
        findings = [
            {"severity": f.severity.value, "type": f.type, "title": f.title}
            for f in db.scalars(
                select(Finding)
                .where(Finding.system_id.in_(system_ids), Finding.status == FindingStatus.OPEN)
                .order_by(Finding.severity)
            )
            if f.type != "low_confidence_classification"
            and not f.type.startswith("special_category")
        ]
        rows.append(
            RegisterRow(
                name=activity.name, system=", ".join(names), status=activity.status.value,
                version=activity.current_version, purposes=list(activity.purposes),
                data_subjects=list(activity.data_subjects), data_categories=list(activity.data_categories),
                recipients=list(activity.recipients), transfers=list(activity.transfers),
                retention=activity.retention or "", security_measures=activity.security_measures or "",
                lawful_basis=activity.lawful_basis or "",
                special_category_condition=activity.special_category_condition or "",
                next_review_date=activity.next_review_date.isoformat() if activity.next_review_date else "",
                citations=activity.citations,
                special_categories=list((latest.snapshot.get("special_categories") if latest else None) or []),
                open_findings=findings,
            )
        )  # fmt: skip
    return rows


@router.get("/exports/register.xlsx")
def export_xlsx(
    request: Request,
    principal: Principal = Depends(require_role(*EXPORTERS)),
    db: TenantSession = Depends(get_tenant_db),
) -> Response:
    rows = _register_rows(db, request, principal)
    content = to_xlsx(rows, _labels(request), date.today())
    write_audit(
        db,
        request,
        "export.register",
        principal=principal,
        details={"format": "xlsx", "records": len(rows)},
    )
    db.commit()
    return Response(
        content,
        media_type=XLSX,
        headers={"Content-Disposition": 'attachment; filename="register-of-processing.xlsx"'},
    )


@router.get("/exports/register.pdf")
def export_pdf(
    request: Request,
    principal: Principal = Depends(require_role(*EXPORTERS)),
    db: TenantSession = Depends(get_tenant_db),
) -> Response:
    rows = _register_rows(db, request, principal)
    content = to_pdf(rows, _labels(request), date.today())
    write_audit(
        db,
        request,
        "export.register",
        principal=principal,
        details={"format": "pdf", "records": len(rows)},
    )
    db.commit()
    return Response(
        content,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="register-of-processing.pdf"'},
    )


# Used by the impact assessment routes.
load_activity = _load
visible_activities = _visible
