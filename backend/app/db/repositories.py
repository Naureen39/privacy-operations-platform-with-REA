"""Repository layer.

Repositories never filter by tenant themselves. Isolation is enforced by Row Level
Security on the session's connection, so a forgotten filter cannot leak data.
"""

import uuid
from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.db.models import AuditLog, Membership, System, User

ModelT = TypeVar("ModelT")


class Repository(Generic[ModelT]):  # noqa: UP046  (explicit TypeVar keeps mypy strict simple)
    model: type[ModelT]

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, entity_id: uuid.UUID) -> ModelT | None:
        return self.session.get(self.model, entity_id)

    def list(
        self,
        *criteria: ColumnElement[bool],
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[ModelT]:
        stmt = select(self.model).where(*criteria).limit(limit).offset(offset)
        return self.session.scalars(stmt).all()

    def count(self, *criteria: ColumnElement[bool]) -> int:
        stmt = select(func.count()).select_from(self.model).where(*criteria)
        return self.session.scalar(stmt) or 0

    def add(self, **values: Any) -> ModelT:
        entity = self.model(**values)
        self.session.add(entity)
        self.session.flush()
        return entity

    def delete(self, entity: ModelT) -> None:
        self.session.delete(entity)
        self.session.flush()


class SystemRepository(Repository[System]):
    model = System

    def get_by_slug(self, slug: str) -> System | None:
        return self.session.scalar(select(System).where(System.slug == slug))

    def list_owned_by(self, user_id: uuid.UUID) -> Sequence[System]:
        return self.list(System.owner_user_id == user_id)


class UserRepository(Repository[User]):
    model = User

    def get_by_email(self, email: str) -> User | None:
        return self.session.scalar(select(User).where(func.lower(User.email) == email.lower()))


class MembershipRepository(Repository[Membership]):
    model = Membership

    def for_user(self, user_id: uuid.UUID) -> Sequence[Membership]:
        return self.list(Membership.user_id == user_id)


class AuditLogRepository(Repository[AuditLog]):
    """Append only: the database role has no UPDATE or DELETE privilege on audit_log."""

    model = AuditLog

    def record(self, action: str, **values: Any) -> AuditLog:
        return self.add(action=action, **values)
