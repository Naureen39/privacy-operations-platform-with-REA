"""Jobs and their events."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.enums import JobStatus
from app.db.models import Job, JobEvent, System

STAGES = ("discover", "classify", "fuse", "record", "screen")
FINISHED = (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED)


def new_job(
    db: Session,
    system: System,
    user_id: uuid.UUID | None,
    stages: tuple[str, ...],
    params: dict[str, Any],
) -> Job:
    job = Job(
        system_id=system.id,
        created_by=user_id,
        stages={s: {"state": "pending", "attempts": 0} for s in stages},
        params=params,
    )
    db.add(job)
    db.flush()
    add_event(db, job, "queued", detail={"stages": list(stages)})
    return job


def add_event(
    db: Session,
    job: Job,
    event: str,
    stage: str | None = None,
    detail: dict[str, Any] | None = None,
) -> JobEvent:
    row = JobEvent(
        job_id=job.id, system_id=job.system_id, stage=stage, event=event, detail=detail or {}
    )
    db.add(row)
    db.flush()
    return row


def set_stage(job: Job, stage: str, **fields: Any) -> None:
    stages = {k: dict(v) for k, v in (job.stages or {}).items()}
    stages[stage] = {**stages.get(stage, {}), **fields}
    job.stages = stages  # a new object, so the change is saved


def ordered(stages: dict[str, Any]) -> list[str]:
    """Stage names in pipeline order (a JSONB column does not keep the order of its keys)."""
    return [s for s in STAGES if s in stages]


def next_stage(job: Job, stage: str) -> str | None:
    order = ordered(job.stages)
    index = order.index(stage)
    return order[index + 1] if index + 1 < len(order) else None


def now() -> datetime:
    return datetime.now(UTC)
