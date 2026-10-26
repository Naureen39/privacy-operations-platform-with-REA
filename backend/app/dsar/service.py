"""The access request workflow: intake, identity check, extension, search, response and approval."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.enums import ApprovalStatus, RequestStatus, ResponseStatus
from app.db.models import (
    AccessRequest,
    ActivitySystem,
    Approval,
    DataElement,
    ProcessingActivity,
    RequestResponse,
    RequestResult,
)
from app.dsar import deadline
from app.dsar.search import Hit, SearchOutcome

ENTITY = "access_request"
TEMPLATES = Path(__file__).resolve().parent / "templates"
CHECKLIST = ("name_matches_records", "contact_details_confirmed", "identity_document_seen")
OPEN = (
    RequestStatus.RECEIVED,
    RequestStatus.IDENTITY_VERIFICATION,
    RequestStatus.SEARCHING,
    RequestStatus.DRAFTING,
    RequestStatus.AWAITING_APPROVAL,
)
CONTACT = "[Contact details of the privacy officer to be added before sending.]"

_env = Environment(
    loader=FileSystemLoader(TEMPLATES),
    undefined=StrictUndefined,
    autoescape=False,  # noqa: S701  (a plain text letter)
    trim_blocks=True,
    lstrip_blocks=True,
)


class RequestWorkflowError(Exception):
    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class ResponseContext:
    reference: str
    today: date
    received: date
    extended: bool
    extension_months: int
    extension_reason: str
    systems: list[dict[str, Any]]
    skipped: list[str]


class RequestService:
    def __init__(self, db: Session, today: date) -> None:
        self.db = db
        self.today = today

    # -- intake ------------------------------------------------------------------------------

    def create(
        self, subject_hash: str, identifier_type: str, received: date, user_id: uuid.UUID | None
    ) -> tuple[AccessRequest, list[str]]:
        if received > self.today:
            raise RequestWorkflowError("The request cannot be received in the future", 422)
        duplicates = [
            r.reference or str(r.id)
            for r in self.db.scalars(
                select(AccessRequest).where(
                    AccessRequest.subject_hash == subject_hash, AccessRequest.status.in_(OPEN)
                )
            )
        ]
        for _ in range(5):
            request = AccessRequest(
                subject_hash=subject_hash,
                identifier_type=identifier_type,
                received_date=received,
                deadline_date=deadline.initial_deadline(received),
                reference=self._next_reference(received.year),
                assigned_to=user_id,
            )
            self.db.add(request)
            try:
                with self.db.begin_nested():
                    self.db.flush()
            except IntegrityError:
                self.db.expunge(request)
                continue
            return request, duplicates
        raise RequestWorkflowError("Could not allocate a reference, try again")

    def _next_reference(self, year: int) -> str:
        prefix = f"AR-{year}-"
        count = self.db.scalar(
            select(func.count())
            .select_from(AccessRequest)
            .where(AccessRequest.reference.like(f"{prefix}%"))
        )
        return f"{prefix}{int(count or 0) + 1:04d}"

    def status_of(self, request: AccessRequest, reminder_days: int) -> deadline.DeadlineStatus:
        closed = request.status not in OPEN
        return deadline.deadline_status(request.deadline_date, self.today, closed, reminder_days)

    # -- identity and extension --------------------------------------------------------------

    def check_identity(
        self, request: AccessRequest, checklist: dict[str, bool], note: str | None
    ) -> bool:
        self._require(
            request,
            (RequestStatus.RECEIVED, RequestStatus.IDENTITY_VERIFICATION, RequestStatus.SEARCHING),
        )
        unknown = set(checklist) - set(CHECKLIST)
        if unknown:
            raise RequestWorkflowError(f"Unknown checklist items: {sorted(unknown)}", 422)
        request.identity_checklist = {
            item: bool(checklist.get(item, False)) for item in CHECKLIST
        } | ({"note": note} if note else {})
        done = all(request.identity_checklist[i] for i in CHECKLIST)
        request.identity_verified = done
        if done:
            if request.status in (RequestStatus.RECEIVED, RequestStatus.IDENTITY_VERIFICATION):
                request.status = RequestStatus.SEARCHING
        elif request.status is RequestStatus.RECEIVED:
            request.status = RequestStatus.IDENTITY_VERIFICATION
        self.db.flush()
        return done

    def extend(self, request: AccessRequest, months: int, reason: str) -> None:
        self._require(request, OPEN)
        ok, why = deadline.can_extend(request.received_date, self.today, request.extended)
        if not ok:
            raise RequestWorkflowError(why)
        if not 1 <= months <= deadline.MAX_EXTENSION_MONTHS:
            raise RequestWorkflowError("An extension is one or two further months", 422)
        if len(reason.strip()) < 10:
            raise RequestWorkflowError(
                "Record the reason for the extension (at least 10 characters)", 422
            )
        request.extended, request.extension_months = True, months
        request.extension_reason = reason.strip()
        request.deadline_date = deadline.extended_deadline(request.received_date, months)
        self.db.flush()

    # -- search and disclosure ---------------------------------------------------------------

    def store_results(self, request: AccessRequest, outcome: SearchOutcome) -> list[RequestResult]:
        self._require(request, (RequestStatus.SEARCHING, RequestStatus.DRAFTING))
        if not request.identity_verified:
            raise RequestWorkflowError("Verify the identity of the person before searching")
        self.db.execute(delete(RequestResult).where(RequestResult.request_id == request.id))
        rows = [
            RequestResult(
                request_id=request.id, system_id=h.system_id, table_name=h.table,
                column_name=h.column, category=h.category, match_count=h.count,
            )
            for h in outcome.hits
        ]  # fmt: skip
        self.db.add_all(rows)
        request.searched_at = datetime.now(UTC)
        request.status = RequestStatus.DRAFTING
        self.db.flush()
        return rows

    def results(self, request_id: uuid.UUID) -> list[RequestResult]:
        return list(
            self.db.scalars(
                select(RequestResult)
                .where(RequestResult.request_id == request_id)
                .order_by(
                    RequestResult.system_id, RequestResult.table_name, RequestResult.column_name
                )
            )
        )

    def approve_disclosure(self, request: AccessRequest, result_ids: list[uuid.UUID]) -> int:
        self._require(request, (RequestStatus.DRAFTING, RequestStatus.AWAITING_APPROVAL))
        count = 0
        for row in self.results(request.id):
            row.disclosure_approved = row.id in set(result_ids)
            count += int(row.disclosure_approved)
        unknown = set(result_ids) - {r.id for r in self.results(request.id)}
        if unknown:
            raise RequestWorkflowError("Some results do not belong to this request", 404)
        self.db.flush()
        return count

    # -- response ----------------------------------------------------------------------------

    def context(
        self,
        request: AccessRequest,
        skipped: list[str],
        names: dict[uuid.UUID, str],
        labels: dict[str, str],
    ) -> ResponseContext:
        by_system: dict[uuid.UUID, list[RequestResult]] = {}
        for r in self.results(request.id):
            by_system.setdefault(r.system_id, []).append(r)
        systems = []
        for system_id, rows in by_system.items():
            tables = sorted({r.table_name for r in rows})
            categories = sorted(
                {
                    labels.get(e.category, e.category)
                    for e in self.db.scalars(
                        select(DataElement).where(DataElement.system_id == system_id)
                    )
                    if e.category and (e.context or {}).get("table") in tables
                }
            )
            activity = self.db.scalars(
                select(ProcessingActivity)
                .join(ActivitySystem, ActivitySystem.activity_id == ProcessingActivity.id)
                .where(ActivitySystem.system_id == system_id)
            ).first()
            systems.append(
                {
                    "name": names.get(system_id, "System"),
                    "locations": "; ".join(f"{t}: {sum(r.match_count for r in rows if r.table_name == t)} record(s)" for t in tables),
                    "categories": categories,
                    "purposes": list(activity.purposes) if activity else [],
                    "recipients": [r.get("vendor", "") for r in activity.recipients] if activity else [],
                    "retention": (activity.retention or "") if activity else "",
                }
            )  # fmt: skip
        systems.sort(key=lambda s: str(s["name"]))
        return ResponseContext(
            reference=request.reference or str(request.id), today=self.today, received=request.received_date,
            extended=request.extended, extension_months=request.extension_months,
            extension_reason=request.extension_reason or "", systems=systems, skipped=skipped,
        )  # fmt: skip

    def render(self, ctx: ResponseContext) -> str:
        return _env.get_template("response.j2").render(
            reference=ctx.reference, date=ctx.today.isoformat(), received=ctx.received.isoformat(),
            extended=ctx.extended, extension_months=ctx.extension_months, extension_reason=ctx.extension_reason,
            systems=ctx.systems, skipped=ctx.skipped, contact=CONTACT,
        ).strip()  # fmt: skip

    def latest_response(self, request_id: uuid.UUID) -> RequestResponse | None:
        return self.db.scalars(
            select(RequestResponse)
            .where(RequestResponse.request_id == request_id)
            .order_by(RequestResponse.version.desc())
        ).first()

    def draft_response(
        self, request: AccessRequest, body: str, cover_note: str | None, user_id: uuid.UUID | None
    ) -> RequestResponse:
        self._require(request, (RequestStatus.DRAFTING,))
        if request.searched_at is None:
            raise RequestWorkflowError("Search the systems before drafting the response")
        previous = self.latest_response(request.id)
        response = RequestResponse(
            request_id=request.id, version=(previous.version + 1) if previous else 1,
            body=body, cover_note=cover_note, created_by=user_id,
        )  # fmt: skip
        self.db.add(response)
        self.db.flush()
        return response

    def edit_response(
        self, request: AccessRequest, body: str | None, cover_note: str | None
    ) -> RequestResponse:
        self._require(request, (RequestStatus.DRAFTING,))
        response = self.latest_response(request.id)
        if response is None or response.status is not ResponseStatus.DRAFT:
            raise RequestWorkflowError("There is no draft response to edit")
        if body is not None:
            response.body = body
        if cover_note is not None:
            response.cover_note = cover_note
        self.db.flush()
        return response

    def submit(self, request: AccessRequest, user_id: uuid.UUID) -> None:
        self._require(request, (RequestStatus.DRAFTING,))
        response = self.latest_response(request.id)
        if response is None or response.status is not ResponseStatus.DRAFT:
            raise RequestWorkflowError("Draft the response first")
        if not request.identity_verified:
            raise RequestWorkflowError("The identity of the person is not verified")
        request.status = RequestStatus.AWAITING_APPROVAL
        self.db.add(Approval(entity_type=ENTITY, entity_id=request.id, requested_by=user_id))
        self.db.flush()

    def decide(
        self, request: AccessRequest, user_id: uuid.UUID, approve: bool, note: str | None
    ) -> None:
        self._require(request, (RequestStatus.AWAITING_APPROVAL,))
        approval = self.db.scalars(
            select(Approval)
            .where(
                Approval.entity_type == ENTITY,
                Approval.entity_id == request.id,
                Approval.status == ApprovalStatus.PENDING,
            )
            .order_by(Approval.created_at.desc())
        ).first()
        if approval is None:
            raise RequestWorkflowError("There is no pending approval")
        if approval.requested_by == user_id:
            raise RequestWorkflowError("The person who submitted the response cannot approve it")
        approval.status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
        approval.decided_by, approval.decided_at, approval.decision_note = (
            user_id,
            datetime.now(UTC),
            note,
        )
        response = self.latest_response(request.id)
        if approve and response is not None:
            response.status = ResponseStatus.APPROVED
        else:
            request.status = RequestStatus.DRAFTING
        self.db.flush()

    def respond(self, request: AccessRequest) -> None:
        self._require(request, (RequestStatus.AWAITING_APPROVAL,))
        response = self.latest_response(request.id)
        if response is None or response.status is not ResponseStatus.APPROVED:
            raise RequestWorkflowError("The response has not been approved")
        response.status = ResponseStatus.SENT
        request.status = RequestStatus.RESPONDED
        request.responded_at = datetime.now(UTC)
        self.db.flush()

    def close(self, request: AccessRequest) -> None:
        self._require(request, (RequestStatus.RESPONDED,))
        request.status = RequestStatus.CLOSED
        request.closed_at = datetime.now(UTC)
        self.db.flush()

    def reject(self, request: AccessRequest, reason: str) -> None:
        self._require(request, OPEN)
        if len(reason.strip()) < 10:
            raise RequestWorkflowError(
                "Record the reason for refusing the request (at least 10 characters)", 422
            )
        request.status = RequestStatus.REJECTED
        request.rejection_reason = reason.strip()
        request.closed_at = datetime.now(UTC)
        self.db.flush()

    def _require(self, request: AccessRequest, allowed: tuple[RequestStatus, ...]) -> None:
        if request.status not in allowed:
            raise RequestWorkflowError(
                f"Not possible while the request is {request.status.value.replace('_', ' ')}"
            )


__all__ = ["CHECKLIST", "Hit", "RequestService", "RequestWorkflowError"]
