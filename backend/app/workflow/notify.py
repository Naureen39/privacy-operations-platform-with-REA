"""In-app notifications. A notification with a `dedupe_key` is created once per user."""

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.enums import Role
from app.db.models import Membership, Notification


def notify(
    db: Session,
    user_id: uuid.UUID | None,
    kind: str,
    title: str,
    body: str | None = None,
    *,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    dedupe_key: str | None = None,
) -> bool:
    """Create a notification. Returns False when one with the same key already exists."""
    if user_id is None:
        return False
    org_id = db.info["tenant_context"].org_id
    if dedupe_key is not None:
        inserted = db.execute(
            pg_insert(Notification)
            .values(
                org_id=org_id, user_id=user_id, kind=kind, title=title[:300], body=body,
                entity_type=entity_type, entity_id=entity_id, dedupe_key=dedupe_key,
            )
            .on_conflict_do_nothing(index_elements=["org_id", "user_id", "dedupe_key"])
            .returning(Notification.id)
        ).first()  # fmt: skip
        return inserted is not None
    db.add(
        Notification(
            user_id=user_id, kind=kind, title=title[:300], body=body, entity_type=entity_type,
            entity_id=entity_id,
        )
    )  # fmt: skip
    db.flush()
    return True


def notify_many(
    db: Session,
    user_ids: Iterable[uuid.UUID | None],
    kind: str,
    title: str,
    body: str | None = None,
    **kw: object,
) -> int:
    seen: set[uuid.UUID] = set()
    created = 0
    for user_id in user_ids:
        if user_id is None or user_id in seen:
            continue
        seen.add(user_id)
        created += int(notify(db, user_id, kind, title, body, **kw))  # type: ignore[arg-type]
    return created


def admins(db: Session) -> list[uuid.UUID]:
    return list(db.scalars(select(Membership.user_id).where(Membership.role == Role.ADMIN)))


def approval_event(
    db: Session,
    entity_type: str,
    entity_id: uuid.UUID,
    name: str,
    action: str,
    actor_id: uuid.UUID | None,
) -> None:
    """Tell the right people about a step of an approval: admins when one is asked for, the person
    who asked when it is decided."""
    from app.db.models import Approval

    if action == "submit":
        notify_many(
            db, [a for a in admins(db) if a != actor_id], "approval_requested",
            f"Approval needed: {name}", entity_type=entity_type, entity_id=entity_id,
        )  # fmt: skip
        return
    if action in ("approve", "reject", "return"):
        requester = db.scalars(
            select(Approval.requested_by)
            .where(Approval.entity_type == entity_type, Approval.entity_id == entity_id)
            .order_by(Approval.created_at.desc())
        ).first()
        verb = {"approve": "approved", "reject": "rejected", "return": "sent back"}[action]
        if requester is not None and requester != actor_id:
            notify(
                db,
                requester,
                "approval_decided",
                f"{name}: {verb}",
                entity_type=entity_type,
                entity_id=entity_id,
            )
