import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select

from app.api.deps import Principal, app_settings, require_role, write_audit
from app.api.pagination import Page, page_params_large, paged
from app.api.schemas import (
    DecisionIn,
    DisclosedLocation,
    DisclosureIn,
    ExtensionIn,
    IdentityIn,
    RejectIn,
    RequestCreate,
    RequestOut,
    RequestResponseOut,
    ResponseDraftIn,
    ResponseEdit,
    ResultOut,
    SearchOut,
    SubjectIn,
)
from app.api.tenancy import get_tenant_db
from app.billing.usage import event_time, record_usage
from app.classify.knowledge import Knowledge
from app.core.config import Settings
from app.db.enums import RequestStatus, Role, UsageKind
from app.db.models import AccessRequest, RequestResponse, RequestResult, System
from app.db.session import TenantSession
from app.dsar import deadline
from app.dsar.hashing import InvalidIdentifierError, matches, normalise, subject_hash, subject_key
from app.dsar.search import SnapshotSearcher
from app.dsar.service import OPEN, RequestService, RequestWorkflowError
from app.llm.errors import LLMError
from app.llm.router import LLMRouter
from app.llm.tasks import Scope, draft_request_cover_note
from app.services.evidence_store import EvidenceStore
from app.workflow.notify import approval_event

router = APIRouter(prefix="/api/v1/access-requests", tags=["access-requests"])

READERS = (Role.ADMIN, Role.ANALYST, Role.VIEWER)
HANDLERS = (Role.ADMIN, Role.ANALYST)


def today_of(settings: Settings) -> date:
    return settings.reference_date or date.today()


def _service(db: TenantSession, settings: Settings) -> RequestService:
    return RequestService(db, today_of(settings))


def _fail(exc: RequestWorkflowError) -> HTTPException:
    return HTTPException(exc.status_code, str(exc))


def _load(db: TenantSession, request_id: uuid.UUID) -> AccessRequest:
    request = db.get(AccessRequest, request_id)
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    return request


def _out(
    db: TenantSession, service: RequestService, request: AccessRequest, settings: Settings,
    duplicates: list[str] | None = None,
) -> RequestOut:  # fmt: skip
    state = service.status_of(request, settings.request_reminder_days)
    results = service.results(request.id)
    return RequestOut(
        id=request.id, reference=request.reference, identifier_type=request.identifier_type,
        status=request.status.value, received_date=request.received_date,
        original_deadline=deadline.initial_deadline(request.received_date),
        deadline_date=request.deadline_date, extended=request.extended,
        extension_months=request.extension_months, extension_reason=request.extension_reason,
        identity_verified=request.identity_verified, identity_checklist=request.identity_checklist,
        days_remaining=state.days_remaining, overdue=state.overdue, reminder=state.level,
        searched_at=request.searched_at, responded_at=request.responded_at, closed_at=request.closed_at,
        rejection_reason=request.rejection_reason,
        systems_matched=len({r.system_id for r in results}), locations_matched=len(results),
        possible_duplicates=duplicates or [],
    )  # fmt: skip


def _names(db: TenantSession) -> dict[uuid.UUID, str]:
    return {s.id: s.name for s in db.scalars(select(System))}


def _result_out(r: RequestResult, names: dict[uuid.UUID, str]) -> ResultOut:
    return ResultOut(
        id=r.id, system_id=r.system_id, system_name=names.get(r.system_id, ""), table=r.table_name,
        column=r.column_name, category=r.category, match_count=r.match_count,
        disclosure_approved=r.disclosure_approved,
    )  # fmt: skip


def _verified_subject(
    request: AccessRequest, settings: Settings, org_id: uuid.UUID, identifier: str
) -> str:
    """The normalised identifier, after checking it is the one this request was opened for."""
    try:
        value = normalise(request.identifier_type, identifier)
        ok = matches(
            subject_key(settings), org_id, request.identifier_type, identifier, request.subject_hash
        )
    except InvalidIdentifierError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not ok:
        raise HTTPException(
            422,
            "The identifier is not the one this request was opened for",
        )
    return value


# -- intake and reading ------------------------------------------------------------------------


@router.post("", response_model=RequestOut, status_code=status.HTTP_201_CREATED)
def create_request(
    request: Request,
    body: RequestCreate,
    principal: Principal = Depends(require_role(*HANDLERS)),
    db: TenantSession = Depends(get_tenant_db),
    settings: Settings = Depends(app_settings),
) -> RequestOut:
    """Open an access request. The identifier is hashed here and the raw value is not kept; the
    deadline is one month from receipt (moved to the next working day)."""
    try:
        digest = subject_hash(
            subject_key(settings),
            principal.org_id,
            body.identifier_type,
            body.identifier.get_secret_value(),
        )
    except InvalidIdentifierError as exc:
        raise HTTPException(422, str(exc)) from exc
    service = _service(db, settings)
    try:
        created, duplicates = service.create(
            digest, body.identifier_type, body.received_date or service.today, principal.user_id
        )
    except RequestWorkflowError as exc:
        raise _fail(exc) from exc
    write_audit(
        db, request, "request.create", principal=principal, entity_type="access_request",
        entity_id=created.id, details={"reference": created.reference, "type": body.identifier_type},
    )  # fmt: skip
    db.commit()
    return _out(db, service, created, settings, duplicates)


@router.get("", response_model=list[RequestOut])
def list_requests(
    response: Response,
    page: Page = Depends(page_params_large),
    status_filter: RequestStatus | None = Query(None, alias="status"),
    open_only: bool = False,
    overdue: bool = False,
    principal: Principal = Depends(require_role(*READERS)),
    db: TenantSession = Depends(get_tenant_db),
    settings: Settings = Depends(app_settings),
) -> list[RequestOut]:
    service = _service(db, settings)
    stmt = select(AccessRequest).order_by(AccessRequest.deadline_date, AccessRequest.created_at)
    if overdue:
        stmt = stmt.where(
            AccessRequest.status.in_(OPEN), AccessRequest.deadline_date < service.today
        )
    if status_filter:
        stmt = stmt.where(AccessRequest.status == status_filter)
    if open_only:
        stmt = stmt.where(AccessRequest.status.in_(OPEN))
    return [_out(db, service, r, settings) for r in paged(db, stmt, page, response)]


@router.get("/reminders", response_model=list[RequestOut])
def reminders(
    principal: Principal = Depends(require_role(*HANDLERS)),
    db: TenantSession = Depends(get_tenant_db),
    settings: Settings = Depends(app_settings),
) -> list[RequestOut]:
    """Open requests that are overdue, due today or due within the reminder period, most urgent first."""
    service = _service(db, settings)
    rows = db.scalars(
        select(AccessRequest)
        .where(AccessRequest.status.in_(OPEN))
        .order_by(AccessRequest.deadline_date)
    )
    return [o for o in (_out(db, service, r, settings) for r in rows) if o.reminder != "none"]


@router.get("/{request_id}", response_model=RequestOut)
def get_request(
    request_id: uuid.UUID,
    principal: Principal = Depends(require_role(*READERS)),
    db: TenantSession = Depends(get_tenant_db),
    settings: Settings = Depends(app_settings),
) -> RequestOut:
    return _out(db, _service(db, settings), _load(db, request_id), settings)


# -- identity, extension -----------------------------------------------------------------------


@router.post("/{request_id}/identity", response_model=RequestOut)
def verify_identity(
    request: Request,
    request_id: uuid.UUID,
    body: IdentityIn,
    principal: Principal = Depends(require_role(*HANDLERS)),
    db: TenantSession = Depends(get_tenant_db),
    settings: Settings = Depends(app_settings),
) -> RequestOut:
    """Record the identity check (a checklist in this demo). Searching needs every item confirmed."""
    item = _load(db, request_id)
    service = _service(db, settings)
    try:
        done = service.check_identity(item, body.checklist, body.note)
    except RequestWorkflowError as exc:
        raise _fail(exc) from exc
    write_audit(
        db,
        request,
        "request.identity",
        principal=principal,
        entity_type="access_request",
        entity_id=item.id,
        details={"verified": done},
    )
    db.commit()
    return _out(db, service, item, settings)


@router.post("/{request_id}/extension", response_model=RequestOut)
def extend_deadline(
    request: Request,
    request_id: uuid.UUID,
    body: ExtensionIn,
    principal: Principal = Depends(require_role(*HANDLERS)),
    db: TenantSession = Depends(get_tenant_db),
    settings: Settings = Depends(app_settings),
) -> RequestOut:
    """Extend the deadline by one or two further months for a complex or numerous request, with a
    recorded reason, within the first month."""
    item = _load(db, request_id)
    service = _service(db, settings)
    try:
        service.extend(item, body.months, body.reason)
    except RequestWorkflowError as exc:
        raise _fail(exc) from exc
    write_audit(
        db,
        request,
        "request.extend",
        principal=principal,
        entity_type="access_request",
        entity_id=item.id,
        details={"months": body.months},
    )
    db.commit()
    return _out(db, service, item, settings)


# -- search and disclosure ---------------------------------------------------------------------


@router.post("/{request_id}/search", response_model=SearchOut)
def search(
    request: Request,
    request_id: uuid.UUID,
    body: SubjectIn,
    principal: Principal = Depends(require_role(*HANDLERS)),
    db: TenantSession = Depends(get_tenant_db),
    settings: Settings = Depends(app_settings),
) -> SearchOut:
    """Search every system's discovered identifier columns. Returns counts per table and column,
    not content. The identifier must be sent again; it is checked against the stored hash and
    used only as a query parameter."""
    item = _load(db, request_id)
    value = _verified_subject(item, settings, principal.org_id, body.identifier.get_secret_value())
    store: EvidenceStore = request.app.state.evidence_store
    service = _service(db, settings)
    if not item.identity_verified:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Verify the identity of the person before searching"
        )
    outcome = SnapshotSearcher(db, store).search(item.identifier_type, value)
    try:
        rows = service.store_results(item, outcome)
    except RequestWorkflowError as exc:
        raise _fail(exc) from exc
    write_audit(
        db, request, "request.search", principal=principal, entity_type="access_request", entity_id=item.id,
        details={"locations": len(rows), "systems": len({r.system_id for r in rows}), "searched": len(outcome.searched), "skipped": len(outcome.skipped)},
    )  # fmt: skip
    db.commit()
    names = _names(db)
    return SearchOut(
        results=[_result_out(r, names) for r in service.results(item.id)],
        searched=[n for _, n in outcome.searched],
        skipped=[{"system": n, "reason": why} for _, n, why in outcome.skipped],
        systems_matched=len({r.system_id for r in rows}),
    )


@router.get("/{request_id}/results", response_model=list[ResultOut])
def get_results(
    request_id: uuid.UUID,
    principal: Principal = Depends(require_role(*READERS)),
    db: TenantSession = Depends(get_tenant_db),
    settings: Settings = Depends(app_settings),
) -> list[ResultOut]:
    _load(db, request_id)
    names = _names(db)
    return [_result_out(r, names) for r in _service(db, settings).results(request_id)]


@router.post("/{request_id}/disclosure", response_model=list[ResultOut])
def approve_disclosure(
    request: Request,
    request_id: uuid.UUID,
    body: DisclosureIn,
    principal: Principal = Depends(require_role(Role.ADMIN)),
    db: TenantSession = Depends(get_tenant_db),
    settings: Settings = Depends(app_settings),
) -> list[ResultOut]:
    """Approve which locations may be disclosed with their content. Everything else stays a count."""
    item = _load(db, request_id)
    service = _service(db, settings)
    try:
        approved = service.approve_disclosure(item, body.result_ids)
    except RequestWorkflowError as exc:
        raise _fail(exc) from exc
    write_audit(
        db,
        request,
        "request.disclosure",
        principal=principal,
        entity_type="access_request",
        entity_id=item.id,
        details={"approved": approved},
    )
    db.commit()
    names = _names(db)
    return [_result_out(r, names) for r in service.results(item.id)]


@router.post("/{request_id}/disclosed-data", response_model=list[DisclosedLocation])
def disclosed_data(
    request: Request,
    request_id: uuid.UUID,
    body: SubjectIn,
    principal: Principal = Depends(require_role(Role.ADMIN)),
    db: TenantSession = Depends(get_tenant_db),
    settings: Settings = Depends(app_settings),
) -> list[DisclosedLocation]:
    """The rows behind the approved locations (at most 50 per table), for the copy of the data. The
    content is read for this call and not stored."""
    item = _load(db, request_id)
    value = _verified_subject(item, settings, principal.org_id, body.identifier.get_secret_value())
    if not item.identity_verified:
        raise HTTPException(status.HTTP_409_CONFLICT, "Verify the identity of the person first")
    store: EvidenceStore = request.app.state.evidence_store
    searcher = SnapshotSearcher(db, store)
    names = _names(db)
    out: list[DisclosedLocation] = []
    for r in _service(db, settings).results(item.id):
        if not r.disclosure_approved or not r.column_name:
            continue
        data: dict[str, Any] | None = searcher.rows(
            r.system_id, r.table_name, r.column_name, item.identifier_type, value
        )
        if data:
            out.append(
                DisclosedLocation(
                    system=names.get(r.system_id, ""),
                    table=r.table_name,
                    column=r.column_name,
                    **data,
                )
            )
    write_audit(
        db,
        request,
        "request.disclosed_data",
        principal=principal,
        entity_type="access_request",
        entity_id=item.id,
        details={"locations": len(out), "rows": sum(len(x.rows) for x in out)},
    )
    db.commit()
    return out


# -- response and approval ---------------------------------------------------------------------


def _response_out(r: RequestResponse) -> RequestResponseOut:
    return RequestResponseOut(
        version=r.version,
        status=r.status.value,
        body=r.body,
        cover_note=r.cover_note,
        created_at=r.created_at,
    )


@router.post(
    "/{request_id}/response", response_model=RequestResponseOut, status_code=status.HTTP_201_CREATED
)
def draft_response(
    request: Request,
    request_id: uuid.UUID,
    body: ResponseDraftIn,
    principal: Principal = Depends(require_role(*HANDLERS)),
    db: TenantSession = Depends(get_tenant_db),
    settings: Settings = Depends(app_settings),
) -> RequestResponseOut:
    """Draft the response letter from the search results and the records of the systems, with an
    optional short cover note from the assistant (counts only: no name, identifier or content)."""
    item = _load(db, request_id)
    service = _service(db, settings)
    knowledge: Knowledge = request.app.state.knowledge
    labels = {c.id: c.label for c in knowledge.categories.values()}
    results = service.results(item.id)
    matched = {r.system_id for r in results}
    store: EvidenceStore = request.app.state.evidence_store
    _, not_covered = SnapshotSearcher(db, store).coverage(item.identifier_type)
    skipped = [name for _, name, _ in not_covered]
    names = _names(db)
    text = service.render(service.context(item, skipped, names, labels))

    note: str | None = None
    tokens = 0
    llm: LLMRouter = request.app.state.llm_router
    if body.cover_note and llm.providers:
        try:
            result, call = draft_request_cover_note(
                llm, Scope(principal.org_id, principal.user_id),
                days_taken=max(0, (service.today - item.received_date).days), systems_found=len(matched),
            )  # fmt: skip
            note, tokens = result.note, call.tokens
        except LLMError:
            note = None
    try:
        response = service.draft_response(item, text, note, principal.user_id)
    except RequestWorkflowError as exc:
        raise _fail(exc) from exc
    write_audit(
        db,
        request,
        "request.response_draft",
        principal=principal,
        entity_type="access_request",
        entity_id=item.id,
        details={"version": response.version, "cover_note": note is not None, "tokens": tokens},
    )
    db.commit()
    return _response_out(response)


@router.get("/{request_id}/response", response_model=RequestResponseOut)
def get_response(
    request_id: uuid.UUID,
    principal: Principal = Depends(require_role(*READERS)),
    db: TenantSession = Depends(get_tenant_db),
    settings: Settings = Depends(app_settings),
) -> RequestResponseOut:
    _load(db, request_id)
    response = _service(db, settings).latest_response(request_id)
    if response is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No response has been drafted")
    return _response_out(response)


@router.patch("/{request_id}/response", response_model=RequestResponseOut)
def edit_response(
    request: Request,
    request_id: uuid.UUID,
    body: ResponseEdit,
    principal: Principal = Depends(require_role(*HANDLERS)),
    db: TenantSession = Depends(get_tenant_db),
    settings: Settings = Depends(app_settings),
) -> RequestResponseOut:
    item = _load(db, request_id)
    try:
        response = _service(db, settings).edit_response(item, body.body, body.cover_note)
    except RequestWorkflowError as exc:
        raise _fail(exc) from exc
    write_audit(
        db,
        request,
        "request.response_edit",
        principal=principal,
        entity_type="access_request",
        entity_id=item.id,
    )
    db.commit()
    return _response_out(response)


def _step(
    request: Request,
    db: TenantSession,
    settings: Settings,
    principal: Principal,
    request_id: uuid.UUID,
    action: str,
    **kw: Any,
) -> RequestOut:
    item = _load(db, request_id)
    service = _service(db, settings)
    try:
        if action == "submit":
            service.submit(item, principal.user_id)
        elif action in ("approve", "return"):
            service.decide(item, principal.user_id, action == "approve", kw.get("note"))
        elif action == "respond":
            service.respond(item)
            record_usage(db, UsageKind.REQUESTS_PROCESSED, at=event_time(settings.reference_date))
        elif action == "close":
            service.close(item)
        elif action == "reject":
            service.reject(item, kw["reason"])
    except RequestWorkflowError as exc:
        raise _fail(exc) from exc
    approval_event(
        db,
        "access_request",
        item.id,
        f"Response to request {item.reference}",
        action,
        principal.user_id,
    )
    write_audit(
        db,
        request,
        f"request.{action}",
        principal=principal,
        entity_type="access_request",
        entity_id=item.id,
    )
    db.commit()
    return _out(db, service, item, settings)


@router.post("/{request_id}/submit", response_model=RequestOut)
def submit_response(
    request: Request, request_id: uuid.UUID,
    principal: Principal = Depends(require_role(*HANDLERS)),
    db: TenantSession = Depends(get_tenant_db), settings: Settings = Depends(app_settings),
) -> RequestOut:  # fmt: skip
    """Send the drafted response for approval."""
    return _step(request, db, settings, principal, request_id, "submit")


@router.post("/{request_id}/approve", response_model=RequestOut)
def approve_response(
    request: Request, request_id: uuid.UUID, body: DecisionIn,
    principal: Principal = Depends(require_role(Role.ADMIN)),
    db: TenantSession = Depends(get_tenant_db), settings: Settings = Depends(app_settings),
) -> RequestOut:  # fmt: skip
    return _step(request, db, settings, principal, request_id, "approve", note=body.note)


@router.post("/{request_id}/return", response_model=RequestOut)
def return_response(
    request: Request, request_id: uuid.UUID, body: DecisionIn,
    principal: Principal = Depends(require_role(Role.ADMIN)),
    db: TenantSession = Depends(get_tenant_db), settings: Settings = Depends(app_settings),
) -> RequestOut:  # fmt: skip
    """Send the response back for changes."""
    return _step(request, db, settings, principal, request_id, "return", note=body.note)


@router.post("/{request_id}/respond", response_model=RequestOut)
def respond(
    request: Request, request_id: uuid.UUID,
    principal: Principal = Depends(require_role(Role.ADMIN)),
    db: TenantSession = Depends(get_tenant_db), settings: Settings = Depends(app_settings),
) -> RequestOut:  # fmt: skip
    """Mark the approved response as sent to the person."""
    return _step(request, db, settings, principal, request_id, "respond")


@router.post("/{request_id}/close", response_model=RequestOut)
def close_request(
    request: Request, request_id: uuid.UUID,
    principal: Principal = Depends(require_role(*HANDLERS)),
    db: TenantSession = Depends(get_tenant_db), settings: Settings = Depends(app_settings),
) -> RequestOut:  # fmt: skip
    return _step(request, db, settings, principal, request_id, "close")


@router.post("/{request_id}/reject", response_model=RequestOut)
def reject_request(
    request: Request, request_id: uuid.UUID, body: RejectIn,
    principal: Principal = Depends(require_role(Role.ADMIN)),
    db: TenantSession = Depends(get_tenant_db), settings: Settings = Depends(app_settings),
) -> RequestOut:  # fmt: skip
    """Refuse a request (for example manifestly unfounded or excessive), with the reason recorded."""
    return _step(request, db, settings, principal, request_id, "reject", reason=body.reason)
