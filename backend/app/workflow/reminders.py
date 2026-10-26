"""Review reminders: records whose review date is near or past, and access requests near their
deadline. Each reminder is a task for the owner and a notification, created once per date."""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.enums import ActivityStatus, RequestStatus, TaskStatus
from app.db.models import AccessRequest, ProcessingActivity, Task
from app.dsar.deadline import deadline_status
from app.workflow.notify import admins, notify, notify_many

LEAD_DAYS = 14
OPEN_REQUESTS = (
    RequestStatus.RECEIVED,
    RequestStatus.IDENTITY_VERIFICATION,
    RequestStatus.SEARCHING,
    RequestStatus.DRAFTING,
    RequestStatus.AWAITING_APPROVAL,
)


@dataclass
class ReminderSummary:
    records_due: int = 0
    records_overdue: int = 0
    tasks_created: int = 0
    notifications_created: int = 0
    requests_flagged: int = 0


def run_review_reminders(
    db: Session, today: date, reminder_days: int = 7, lead_days: int = LEAD_DAYS
) -> ReminderSummary:
    summary = ReminderSummary()
    org_admins = admins(db)
    horizon = today + timedelta(days=lead_days)
    org_id = db.info["tenant_context"].org_id

    for activity in db.scalars(
        select(ProcessingActivity).where(
            ProcessingActivity.status != ActivityStatus.ARCHIVED,
            ProcessingActivity.next_review_date.is_not(None),
            ProcessingActivity.next_review_date <= horizon,
        )
    ):
        due = activity.next_review_date
        assert due is not None  # noqa: S101
        overdue = due < today
        summary.records_overdue += int(overdue)
        summary.records_due += int(not overdue)
        assignee = activity.owner_user_id or (org_admins[0] if org_admins else None)
        key = f"review:{activity.id}:{due.isoformat()}"
        inserted = db.execute(
            pg_insert(Task)
            .values(
                org_id=org_id, title=f"Review the record: {activity.name}"[:300],
                description=("Overdue since " if overdue else "Due on ") + due.isoformat() + ". Check the record against the current system and confirm or update it.",
                assignee_user_id=assignee, status=TaskStatus.OPEN.value, due_date=due, dedupe_key=key,
            )
            .on_conflict_do_nothing(index_elements=["org_id", "dedupe_key"])
            .returning(Task.id)
        ).first()  # fmt: skip
        summary.tasks_created += int(inserted is not None)
        level = "overdue" if overdue else "upcoming"
        recipients = [assignee, *(org_admins if overdue else [])]
        summary.notifications_created += notify_many(
            db, recipients, "review_due",
            f"Record review {'overdue' if overdue else 'due soon'}: {activity.name}",
            f"Review date {due.isoformat()}.", entity_type="processing_activity", entity_id=activity.id,
            dedupe_key=f"{key}:{level}",
        )  # fmt: skip

    for request in db.scalars(select(AccessRequest).where(AccessRequest.status.in_(OPEN_REQUESTS))):
        state = deadline_status(
            request.deadline_date, today, closed=False, reminder_days=reminder_days
        )
        if state.level == "none":
            continue
        summary.requests_flagged += 1
        recipients_r = [request.assigned_to, *org_admins]
        summary.notifications_created += notify_many(
            db, recipients_r, "request_deadline",
            f"Access request {request.reference or request.id} is {state.level.replace('_', ' ')}",
            f"Deadline {request.deadline_date.isoformat()} ({state.days_remaining} days).",
            entity_type="access_request", entity_id=request.id,
            dedupe_key=f"request:{request.id}:{state.level}:{request.deadline_date.isoformat()}",
        )  # fmt: skip
    db.flush()
    return summary


__all__ = ["ReminderSummary", "run_review_reminders", "notify", "uuid"]
