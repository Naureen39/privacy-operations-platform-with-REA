"""The onboarding of a system as a chain of idempotent stage tasks.

`onboarding_stage(job_id, org_id, stage)` runs one stage and then queues the next. A stage that
already succeeded is skipped, so a redelivered message does no harm. Transient failures (the
database, the network, no provider) are retried with a growing delay; anything else fails the job
and tells the person who started it. Every transition writes a job event.
"""

import uuid
from dataclasses import asdict
from typing import Any

from celery import Task as CeleryTask
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.db.enums import JobState, JobStatus
from app.db.models import Job, System
from app.db.session import TenantContext, tenant_session
from app.dpia.screening import Scale
from app.llm.errors import LLMUnavailableError
from app.services import pipeline
from app.workers import jobs
from app.workers.celery_app import celery_app
from app.workers.runtime import Runtime, get_runtime
from app.workflow.notify import admins, notify_many
from app.workflow.reminders import run_review_reminders

TRANSIENT = (OperationalError, OSError, ConnectionError, TimeoutError, LLMUnavailableError)


def dispatch(settings: Settings, job_id: str, org_id: str, stage: str) -> None:
    """Queue a stage for a worker, or run it here when tasks are eager (tests, a laptop without a
    broker). The choice follows the settings of the caller, not global Celery state."""
    if settings.celery_eager:
        onboarding_stage.apply(args=[job_id, org_id, stage])
    else:
        onboarding_stage.delay(job_id, org_id, stage)


def execute_stage(db: Any, rt: Runtime, job: Job, system: System, stage: str) -> dict[str, Any]:
    org_id, user_id = job.org_id, job.created_by
    if stage == "discover":
        return pipeline.discover(db, rt, system, user_id)
    if stage == "classify":
        return pipeline.classify(db, rt, system)
    if stage == "fuse":
        return pipeline.fuse(db, rt, system, org_id, user_id)
    if stage == "record":
        outcome = pipeline.generate_record(db, rt, system, org_id, user_id)
        return {
            "activity_id": str(outcome.result.activity.id),
            "created": outcome.result.created,
            "changed": outcome.result.changed,
            "version": outcome.result.version,
            "suggestion_used": outcome.suggestion_used,
            "tokens": outcome.tokens,
        }
    if stage == "screen":
        scale = job.params.get("scale")
        return pipeline.screen(db, rt, system, org_id, user_id, Scale(**scale) if scale else None)
    raise pipeline.StageError(f"Unknown stage: {stage}")


@celery_app.task(bind=True, name="onboarding.stage", acks_late=True, ignore_result=True)
def onboarding_stage(self: CeleryTask, job_id: str, org_id: str, stage: str) -> str:
    rt = get_runtime()
    org = uuid.UUID(org_id)
    job_uuid = uuid.UUID(job_id)

    # 1. claim the stage
    skipped_to: str | None = None
    already_done = False
    with tenant_session(rt.session_factory, TenantContext(org_id=org)) as db:
        job = db.get(Job, job_uuid)
        if job is None:
            return "missing"
        if job.state in jobs.FINISHED:
            return job.state.value
        creator = job.created_by
        if job.stages.get(stage, {}).get("state") == "succeeded":
            already_done = True
            skipped_to = jobs.next_stage(job, stage)
            jobs.add_event(db, job, "stage_skipped", stage, {"reason": "already done"})
        else:
            attempts = int(job.stages.get(stage, {}).get("attempts", 0)) + 1
            if job.state is JobStatus.QUEUED:
                job.state, job.started_at = JobStatus.RUNNING, jobs.now()
                jobs.add_event(db, job, "started")
            jobs.set_stage(
                job, stage, state="running", attempts=attempts, started_at=jobs.now().isoformat()
            )
            jobs.add_event(db, job, "stage_started", stage, {"attempt": attempts})
    if already_done:
        if skipped_to is not None:
            dispatch(rt.settings, job_id, org_id, skipped_to)
        return "skipped"

    # 2. do the work in its own transaction
    try:
        with tenant_session(rt.session_factory, TenantContext(org_id=org, user_id=creator)) as db:
            work_job = db.get(Job, job_uuid)
            system = db.get(System, work_job.system_id) if work_job else None
            if work_job is None or system is None:
                raise pipeline.StageError("The system no longer exists")
            result = execute_stage(db, rt, work_job, system, stage)
    except TRANSIENT as exc:
        retries = self.request.retries
        if retries < rt.settings.job_max_retries:
            with tenant_session(rt.session_factory, TenantContext(org_id=org)) as db:
                job = db.get(Job, job_uuid)
                if job is not None:
                    jobs.set_stage(job, stage, state="retrying")
                    jobs.add_event(
                        db, job, "retry", stage, {"error": type(exc).__name__, "retry": retries + 1}
                    )
            raise self.retry(
                exc=exc,
                countdown=rt.settings.job_retry_seconds * (2**retries),
                max_retries=rt.settings.job_max_retries,
            ) from exc
        _fail(rt, org, job_uuid, stage, f"{type(exc).__name__}: gave up after {retries} retries")
        return "failed"
    except Exception as exc:
        _fail(rt, org, job_uuid, stage, str(exc)[:500] or type(exc).__name__)
        return "failed"

    # 3. record the result and queue the next stage
    following: str | None = None
    with tenant_session(rt.session_factory, TenantContext(org_id=org)) as db:
        job = db.get(Job, job_uuid)
        if job is None:
            return "missing"
        jobs.set_stage(
            job, stage, state="succeeded", finished_at=jobs.now().isoformat(), result=result
        )
        jobs.add_event(db, job, "stage_succeeded", stage, {"result": _short(result)})
        following = jobs.next_stage(job, stage)
        if following is None:
            job.state, job.finished_at = JobStatus.SUCCEEDED, jobs.now()
            job.result = {s: v.get("result", {}) for s, v in job.stages.items()}
            jobs.add_event(db, job, "succeeded")
            system = db.get(System, job.system_id)
            notify_many(
                db,
                [job.created_by, system.owner_user_id if system else None],
                "job_succeeded",
                f"Onboarding finished: {system.name if system else 'system'}",
                "Discovery, classification, comparison, the record and the screening are done.",
                entity_type="job",
                entity_id=job.id,
                dedupe_key=f"job:{job.id}:done",
            )
    if following is not None:
        dispatch(rt.settings, job_id, org_id, following)
    return "done" if following is None else "next"


def _fail(rt: Runtime, org_id: uuid.UUID, job_id: uuid.UUID, stage: str, message: str) -> None:
    with tenant_session(rt.session_factory, TenantContext(org_id=org_id)) as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        jobs.set_stage(
            job, stage, state="failed", error=message, finished_at=jobs.now().isoformat()
        )
        job.state, job.error, job.finished_at = JobStatus.FAILED, f"{stage}: {message}", jobs.now()
        jobs.add_event(db, job, "stage_failed", stage, {"error": message})
        jobs.add_event(db, job, "failed", detail={"stage": stage})
        system = db.get(System, job.system_id)
        if system is not None:
            system.status = JobState.FAILED
        notify_many(
            db,
            [job.created_by, *admins(db)],
            "job_failed",
            f"Onboarding failed at {stage}: {system.name if system else 'system'}",
            message,
            entity_type="job",
            entity_id=job.id,
            dedupe_key=f"job:{job.id}:failed",
        )


def _short(result: dict[str, Any]) -> dict[str, Any]:
    """Event details stay small: the scalar values of the stage result only."""
    return {k: v for k, v in result.items() if isinstance(v, (str, int, float, bool)) or v is None}


@celery_app.task(name="workflow.review_reminders")
def review_reminders(org_id: str) -> dict[str, int]:
    rt = get_runtime()
    with tenant_session(rt.session_factory, TenantContext(org_id=uuid.UUID(org_id))) as db:
        summary = run_review_reminders(
            db, pipeline.today_of(rt.settings), rt.settings.request_reminder_days
        )
    return asdict(summary)


@celery_app.task(name="workflow.review_reminders_all")
def review_reminders_all() -> int:
    """Fan out to every organisation. Listing organisations needs the owner role, so they are read
    with the migration connection; each organisation's reminders then run as the application."""
    from sqlalchemy import create_engine, text

    rt = get_runtime()
    engine = create_engine(rt.settings.migration_database_url)
    try:
        with engine.connect() as conn:
            org_ids = [str(r[0]) for r in conn.execute(text("SELECT id FROM organizations"))]
    finally:
        engine.dispose()
    for org_id in org_ids:
        review_reminders.delay(org_id)
    return len(org_ids)


def _owner_engine(rt: Runtime) -> Any:
    from sqlalchemy import create_engine

    return create_engine(rt.settings.migration_database_url)


@celery_app.task(name="analytics.nightly")
def analytics_nightly(days: int = 3) -> dict[str, int]:
    """Write the compliance and platform snapshots (reads every organisation, so it connects as
    the database owner; the numbers it stores are aggregates, no tenant rows leave the database)."""
    from app.analytics import nightly

    rt = get_runtime()
    owner = _owner_engine(rt)
    try:
        summary = nightly.run_nightly(
            owner, rt.session_factory, pipeline.today_of(rt.settings), days
        )
    finally:
        owner.dispose()
    return asdict(summary)


@celery_app.task(name="billing.invoice_run_all")
def billing_invoice_run_all() -> dict[str, int]:
    """On the first of the month: invoice the month that ended, for every organisation."""
    from app.analytics import nightly

    rt = get_runtime()
    owner = _owner_engine(rt)
    try:
        summary = nightly.run_invoices(owner, rt.session_factory, pipeline.today_of(rt.settings))
    finally:
        owner.dispose()
    return asdict(summary)
