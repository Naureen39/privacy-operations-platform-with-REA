import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import Select, func, or_, select, update

from app.api.deps import (
    ALL_ROLES,
    Principal,
    app_settings,
    get_visible_system,
    require_role,
    write_audit,
)
from app.api.pagination import Page, page_params, paged
from app.api.routes.records import load_activity
from app.api.schemas import (
    CommentCreate,
    CommentOut,
    NotificationOut,
    ReminderSummaryOut,
    TaskCreate,
    TaskOut,
    TaskPatch,
)
from app.api.tenancy import get_tenant_db
from app.core.config import Settings
from app.db.enums import FindingStatus, Role, TaskStatus
from app.db.models import Comment, Dpia, Finding, Membership, Notification, System, Task
from app.db.session import TenantSession
from app.services.pipeline import today_of
from app.workflow.notify import notify, notify_many
from app.workflow.reminders import run_review_reminders

router = APIRouter(prefix="/api/v1", tags=["workflow"])

EDITORS = (Role.ADMIN, Role.ANALYST)
COMMENTERS = (Role.ADMIN, Role.ANALYST, Role.SYSTEM_OWNER)


# -- tasks -------------------------------------------------------------------------------------


def _visible_tasks(principal: Principal) -> Select[Any]:
    stmt = select(Task)
    if principal.role is Role.SYSTEM_OWNER:
        owned = select(System.id).where(System.owner_user_id == principal.user_id)
        stmt = stmt.where(
            or_(Task.assignee_user_id == principal.user_id, Task.system_id.in_(owned))
        )
    return stmt


def _task(db: TenantSession, principal: Principal, task_id: uuid.UUID) -> Task:
    task: Task | None = db.scalars(_visible_tasks(principal).where(Task.id == task_id)).first()
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    return task


def _member(db: TenantSession, user_id: uuid.UUID | None) -> None:
    if (
        user_id is not None
        and db.scalar(select(Membership.id).where(Membership.user_id == user_id)) is None
    ):
        raise HTTPException(422, "The assignee is not in this organization")


@router.post("/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(
    request: Request,
    body: TaskCreate,
    principal: Principal = Depends(require_role(*EDITORS)),
    db: TenantSession = Depends(get_tenant_db),
) -> Task:
    _member(db, body.assignee_user_id)
    if body.system_id:
        get_visible_system(db, principal, body.system_id)
    if body.finding_id and db.get(Finding, body.finding_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")
    task = Task(**body.model_dump(), status=TaskStatus.OPEN)
    db.add(task)
    db.flush()
    if task.assignee_user_id and task.assignee_user_id != principal.user_id:
        notify(
            db,
            task.assignee_user_id,
            "task_assigned",
            f"New task: {task.title}",
            task.description,
            entity_type="task",
            entity_id=task.id,
        )
    write_audit(
        db, request, "task.create", principal=principal, entity_type="task", entity_id=task.id
    )
    db.commit()
    return task


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(
    response: Response,
    mine: bool = False,
    status_filter: TaskStatus | None = Query(None, alias="status"),
    system_id: uuid.UUID | None = None,
    page: Page = Depends(page_params),
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
) -> list[Task]:
    stmt = _visible_tasks(principal).order_by(
        Task.due_date.asc().nulls_last(), Task.created_at.desc()
    )
    if mine:
        stmt = stmt.where(Task.assignee_user_id == principal.user_id)
    if status_filter:
        stmt = stmt.where(Task.status == status_filter)
    if system_id:
        stmt = stmt.where(Task.system_id == system_id)
    return paged(db, stmt, page, response)


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(
    task_id: uuid.UUID,
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
) -> Task:
    return _task(db, principal, task_id)


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(
    request: Request,
    task_id: uuid.UUID,
    body: TaskPatch,
    principal: Principal = Depends(require_role(*COMMENTERS)),
    db: TenantSession = Depends(get_tenant_db),
) -> Task:
    """Editors change anything; the person a task is assigned to can change its status."""
    task = _task(db, principal, task_id)
    changes = body.model_dump(exclude_unset=True)
    if principal.role is Role.SYSTEM_OWNER and (
        task.assignee_user_id != principal.user_id or set(changes) - {"status"}
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You can only change the status of your own tasks"
        )
    if "assignee_user_id" in changes:
        _member(db, changes["assignee_user_id"])
    for name, value in changes.items():
        setattr(task, name, TaskStatus(value) if name == "status" else value)
    if (
        "assignee_user_id" in changes
        and task.assignee_user_id
        and task.assignee_user_id != principal.user_id
    ):
        notify(
            db,
            task.assignee_user_id,
            "task_assigned",
            f"Task assigned to you: {task.title}",
            task.description,
            entity_type="task",
            entity_id=task.id,
            dedupe_key=f"task:{task.id}:assigned:{task.assignee_user_id}",
        )
    write_audit(
        db,
        request,
        "task.update",
        principal=principal,
        entity_type="task",
        entity_id=task.id,
        details={"fields": sorted(changes)},
    )
    db.commit()
    return task


@router.post("/findings/{finding_id}/task", response_model=TaskOut)
def task_from_finding(
    request: Request,
    finding_id: uuid.UUID,
    response: Response,
    principal: Principal = Depends(require_role(*EDITORS)),
    db: TenantSession = Depends(get_tenant_db),
) -> Task:
    """Turn a finding into a task for the owner of its system. Asking again returns the same task."""
    finding = db.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")
    key = f"finding:{finding.id}"
    existing = db.scalars(select(Task).where(Task.dedupe_key == key)).first()
    if existing is not None:
        return existing
    system = db.get(System, finding.system_id) if finding.system_id else None
    task = Task(
        title=f"Resolve: {finding.title}"[:300], description=finding.suggested_fix or finding.description,
        assignee_user_id=system.owner_user_id if system else None, system_id=finding.system_id,
        finding_id=finding.id, status=TaskStatus.OPEN, dedupe_key=key,
    )  # fmt: skip
    db.add(task)
    db.flush()
    if finding.status is FindingStatus.OPEN:
        finding.status = FindingStatus.ACKNOWLEDGED
    notify(
        db,
        task.assignee_user_id,
        "task_assigned",
        f"New task: {task.title}",
        task.description,
        entity_type="task",
        entity_id=task.id,
    )
    write_audit(
        db,
        request,
        "task.from_finding",
        principal=principal,
        entity_type="finding",
        entity_id=finding.id,
    )
    db.commit()
    response.status_code = status.HTTP_201_CREATED
    return task


# -- comments ----------------------------------------------------------------------------------


def _check_entity(
    db: TenantSession, principal: Principal, entity_type: str, entity_id: uuid.UUID
) -> uuid.UUID | None:
    """The entity must exist and be visible to the person; returns whom to tell (its owner)."""
    if entity_type == "system":
        return get_visible_system(db, principal, entity_id).owner_user_id
    if entity_type == "activity":
        return load_activity(db, principal, entity_id).owner_user_id
    if entity_type == "dpia":
        dpia = db.get(Dpia, entity_id)
        if dpia is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Assessment not found")
        return load_activity(db, principal, dpia.activity_id).owner_user_id
    finding = db.get(Finding, entity_id)
    system = db.get(System, finding.system_id) if finding and finding.system_id else None
    if finding is None or (
        principal.role is Role.SYSTEM_OWNER
        and (system is None or system.owner_user_id != principal.user_id)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")
    return system.owner_user_id if system else None


@router.post("/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
def add_comment(
    request: Request,
    body: CommentCreate,
    principal: Principal = Depends(require_role(*COMMENTERS)),
    db: TenantSession = Depends(get_tenant_db),
) -> Comment:
    owner = _check_entity(db, principal, body.entity_type, body.entity_id)
    comment = Comment(
        entity_type=body.entity_type,
        entity_id=body.entity_id,
        author_user_id=principal.user_id,
        body=body.body,
    )
    db.add(comment)
    db.flush()
    earlier = set(
        db.scalars(
            select(Comment.author_user_id).where(
                Comment.entity_type == body.entity_type, Comment.entity_id == body.entity_id
            )
        )
    )
    recipients = ({owner} | earlier) - {principal.user_id, None}
    notify_many(
        db, recipients, "comment", f"New comment on a {body.entity_type}", body.body[:200],
        entity_type=body.entity_type, entity_id=body.entity_id,
    )  # fmt: skip
    write_audit(
        db,
        request,
        "comment.add",
        principal=principal,
        entity_type=body.entity_type,
        entity_id=body.entity_id,
    )
    db.commit()
    return comment


@router.get("/comments", response_model=list[CommentOut])
def list_comments(
    response: Response,
    entity_type: str = Query(max_length=40),
    entity_id: uuid.UUID = Query(),
    page: Page = Depends(page_params),
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
) -> list[Comment]:
    if entity_type not in ("system", "activity", "dpia", "finding"):
        raise HTTPException(422, "Unknown entity type")
    _check_entity(db, principal, entity_type, entity_id)
    stmt = (
        select(Comment)
        .where(Comment.entity_type == entity_type, Comment.entity_id == entity_id)
        .order_by(Comment.created_at)
    )
    return paged(db, stmt, page, response)


# -- notifications -----------------------------------------------------------------------------


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(
    response: Response,
    unread_only: bool = False,
    page: Page = Depends(page_params),
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
) -> list[Notification]:
    mine = Notification.user_id == principal.user_id
    unread = (
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(mine, Notification.read_at.is_(None))
        )
        or 0
    )
    response.headers["X-Unread-Count"] = str(unread)
    stmt = (
        select(Notification).where(mine).order_by(Notification.created_at.desc(), Notification.id)
    )
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    return paged(db, stmt, page, response)


@router.post("/notifications/read-all", response_model=dict[str, int])
def read_all_notifications(
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
) -> dict[str, int]:
    result = db.execute(
        update(Notification)
        .where(Notification.user_id == principal.user_id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    db.commit()
    return {"marked": result.rowcount or 0}  # type: ignore[attr-defined]


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
def read_notification(
    notification_id: uuid.UUID,
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
) -> Notification:
    item = db.scalars(
        select(Notification).where(
            Notification.id == notification_id, Notification.user_id == principal.user_id
        )
    ).first()
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    if item.read_at is None:
        item.read_at = datetime.now(UTC)
    db.commit()
    return item


# -- reminders ---------------------------------------------------------------------------------


@router.post("/reminders/run", response_model=ReminderSummaryOut)
def run_reminders(
    request: Request,
    principal: Principal = Depends(require_role(Role.ADMIN)),
    db: TenantSession = Depends(get_tenant_db),
    settings: Settings = Depends(app_settings),
) -> ReminderSummaryOut:
    """Create tasks and notifications for records past or near their review date and for access
    requests near their deadline. The same job runs daily in the worker; running it twice creates
    nothing new."""
    summary = run_review_reminders(db, today_of(settings), settings.request_reminder_days)
    write_audit(db, request, "reminders.run", principal=principal, details=asdict(summary))
    db.commit()
    return ReminderSummaryOut(**asdict(summary))
