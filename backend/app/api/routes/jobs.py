import json
import time
import uuid
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import Select, select

from app.api.deps import ALL_ROLES, Principal, get_visible_system, require_role, write_audit
from app.api.pagination import Page, page_params, paged
from app.api.schemas import JobEventOut, JobOut, OnboardIn
from app.api.tenancy import get_tenant_db
from app.db.enums import EvidenceKind, JobStatus, Role
from app.db.models import EvidenceItem, Job, JobEvent, System
from app.db.session import TenantContext, TenantSession, tenant_session
from app.workers import jobs as job_helpers
from app.workers.runtime import runtime_from_state, set_runtime
from app.workers.tasks import dispatch

router = APIRouter(prefix="/api/v1", tags=["jobs"])

RUNNERS = (Role.ADMIN, Role.ANALYST)
STREAM_SECONDS = 300
POLL_SECONDS = 0.4


def _out(job: Job) -> JobOut:
    stages = {name: (job.stages or {})[name] for name in job_helpers.ordered(job.stages or {})}
    done = sum(1 for s in stages.values() if s.get("state") == "succeeded")
    return JobOut(
        id=job.id, system_id=job.system_id, kind=job.kind, state=job.state.value, stages=stages,
        result=job.result, error=job.error, progress={"done": done, "total": len(stages)},
        created_at=job.created_at, started_at=job.started_at, finished_at=job.finished_at,
    )  # fmt: skip


def _visible(principal: Principal) -> Select[Any]:
    stmt = select(Job)
    if principal.role is Role.SYSTEM_OWNER:
        stmt = stmt.where(
            Job.system_id.in_(select(System.id).where(System.owner_user_id == principal.user_id))
        )
    return stmt


def _load(db: TenantSession, principal: Principal, job_id: uuid.UUID) -> Job:
    job: Job | None = db.scalars(_visible(principal).where(Job.id == job_id)).first()
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return job


@router.post(
    "/systems/{system_id}/onboard", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED
)
def start_onboarding(
    request: Request,
    system_id: uuid.UUID,
    body: OnboardIn | None = None,
    principal: Principal = Depends(require_role(*RUNNERS)),
    db: TenantSession = Depends(get_tenant_db),
) -> JobOut:
    """Queue the onboarding of a system: discovery, classification, the comparison, the record and
    the impact assessment screening, each as a retried, idempotent background step. Follow the
    progress with `GET /jobs/{id}/events`."""
    system = get_visible_system(db, principal, system_id)
    body = body or OnboardIn()
    wanted: tuple[str, ...] = tuple(body.stages) if body.stages else job_helpers.STAGES
    stages: tuple[str, ...] = tuple(s for s in job_helpers.STAGES if s in wanted)  # pipeline order
    if (
        db.scalar(
            select(EvidenceItem.id)
            .where(
                EvidenceItem.system_id == system.id,
                EvidenceItem.kind != EvidenceKind.PRIVACY_POLICY,
            )
            .limit(1)
        )
        is None
        and "discover" in stages
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "Attach evidence to the system first")
    running = db.scalar(
        select(Job.id).where(
            Job.system_id == system.id, Job.state.in_([JobStatus.QUEUED, JobStatus.RUNNING])
        )
    )
    if running is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"A job is already running for this system ({running})"
        )
    params: dict[str, Any] = {"scale": body.scale.model_dump() if body.scale else None}
    job = job_helpers.new_job(db, system, principal.user_id, stages, params)
    write_audit(
        db,
        request,
        "job.start",
        principal=principal,
        entity_type="system",
        entity_id=system.id,
        details={"job": str(job.id), "stages": list(stages)},
    )
    db.commit()
    settings = request.app.state.settings
    if (
        settings.celery_eager
    ):  # tasks run in this process, so they must use this application's parts
        set_runtime(runtime_from_state(request.app.state, request.app.state.session_factory))
    try:
        dispatch(settings, str(job.id), str(principal.org_id), stages[0])
    except Exception as exc:  # the queue is unreachable: say so, and do not leave a job waiting
        job = db.get(Job, job.id) or job
        job.state, job.error, job.finished_at = (
            JobStatus.FAILED,
            "The job queue is not reachable",
            job_helpers.now(),
        )
        job_helpers.add_event(db, job, "failed", detail={"error": type(exc).__name__})
        db.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The job queue is not reachable; try again shortly"
        ) from exc
    db.refresh(job)
    return _out(job)


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(
    response: Response,
    system_id: uuid.UUID | None = None,
    state: JobStatus | None = None,
    page: Page = Depends(page_params),
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
) -> list[JobOut]:
    stmt = _visible(principal).order_by(Job.created_at.desc())
    if system_id:
        stmt = stmt.where(Job.system_id == system_id)
    if state:
        stmt = stmt.where(Job.state == state)
    return [_out(j) for j in paged(db, stmt, page, response)]


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(
    job_id: uuid.UUID,
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
) -> JobOut:
    return _out(_load(db, principal, job_id))


@router.get("/jobs/{job_id}/log", response_model=list[JobEventOut])
def job_log(
    job_id: uuid.UUID,
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
) -> list[JobEvent]:
    """Every event of a job, oldest first (the same events the stream sends)."""
    _load(db, principal, job_id)
    return list(
        db.scalars(select(JobEvent).where(JobEvent.job_id == job_id).order_by(JobEvent.seq))
    )


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(
    request: Request,
    job_id: uuid.UUID,
    principal: Principal = Depends(require_role(*RUNNERS)),
    db: TenantSession = Depends(get_tenant_db),
) -> JobOut:
    """Stop a job before its next stage; the stage that is running finishes."""
    job = _load(db, principal, job_id)
    if job.state in job_helpers.FINISHED:
        raise HTTPException(status.HTTP_409_CONFLICT, f"The job has already {job.state.value}")
    job.state, job.finished_at = JobStatus.CANCELLED, job_helpers.now()
    job_helpers.add_event(db, job, "cancelled", detail={"by": str(principal.user_id)})
    write_audit(db, request, "job.cancel", principal=principal, entity_type="job", entity_id=job.id)
    db.commit()
    return _out(job)


def _frame(event: JobEvent) -> str:
    data = {"stage": event.stage, "detail": event.detail, "at": event.created_at.isoformat()}
    return f"id: {event.seq}\nevent: {event.event}\ndata: {json.dumps(data)}\n\n"


def _stream(request: Request, ctx: TenantContext, job_id: uuid.UUID, last_id: int) -> Iterator[str]:
    factory = request.app.state.session_factory
    deadline = time.monotonic() + STREAM_SECONDS
    last = last_id
    while True:
        with tenant_session(factory, ctx) as db:
            rows = list(
                db.scalars(
                    select(JobEvent)
                    .where(JobEvent.job_id == job_id, JobEvent.seq > last)
                    .order_by(JobEvent.seq)
                )
            )
            job = db.get(Job, job_id)
            finished = job is None or job.state in job_helpers.FINISHED
            state = job.state.value if job else "missing"
        for row in rows:
            last = row.seq
            yield _frame(row)
        if finished and not rows:
            yield f"event: end\ndata: {json.dumps({'state': state})}\n\n"
            return
        if time.monotonic() > deadline:
            yield ": stream closed, reconnect with Last-Event-ID\n\n"
            return
        if not rows:
            yield ": keep-alive\n\n"
        time.sleep(POLL_SECONDS)


@router.get("/jobs/{job_id}/events")
def job_events(
    request: Request,
    job_id: uuid.UUID,
    last_event_id: int | None = Header(default=None, alias="Last-Event-ID"),
    after: int = Query(0, ge=0, description="Only events after this sequence number"),
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
) -> StreamingResponse:
    """Server-Sent Events: one event per transition of the job, ending with `end`. A client that
    reconnects sends `Last-Event-ID` and receives only what it missed."""
    _load(db, principal, job_id)
    ctx = TenantContext(org_id=principal.org_id, user_id=principal.user_id)
    return StreamingResponse(
        _stream(request, ctx, job_id, last_event_id if last_event_id is not None else after),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
