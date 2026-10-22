"""Records of processing: creation from a draft, edits, versions and the review workflow."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import ActivityStatus, ApprovalStatus, JobState
from app.db.models import (
    ActivitySystem,
    ActivityVersion,
    Approval,
    ProcessingActivity,
    System,
)
from app.records.builder import Draft, completeness
from app.records.diff import SNAPSHOT_FIELDS, diff_snapshots, summarize

EDITABLE = (
    "purposes",
    "data_subjects",
    "data_categories",
    "lawful_basis",
    "special_category_condition",
    "retention",
    "security_measures",
    "next_review_date",
)
ENTITY = "processing_activity"


class WorkflowError(Exception):
    def __init__(self, message: str, missing: list[str] | None = None) -> None:
        super().__init__(message)
        self.missing = missing or []


@dataclass
class GenerateResult:
    activity: ProcessingActivity
    created: bool
    changed: bool
    version: int


def snapshot_of(activity: ProcessingActivity, special: list[str] | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "name": activity.name,
        "purposes": list(activity.purposes),
        "data_subjects": list(activity.data_subjects),
        "data_categories": list(activity.data_categories),
        "recipients": activity.recipients,
        "transfers": activity.transfers,
        "retention": activity.retention,
        "security_measures": activity.security_measures,
        "lawful_basis": activity.lawful_basis,
        "special_category_condition": activity.special_category_condition,
        "owner_user_id": str(activity.owner_user_id) if activity.owner_user_id else None,
        "next_review_date": activity.next_review_date.isoformat() if activity.next_review_date else None,
        "citations": activity.citations,
    }  # fmt: skip
    if special is not None:
        data["special_categories"] = special
    return data


class ActivityService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # -- lookups -----------------------------------------------------------------------------

    def for_system(self, system_id: uuid.UUID) -> ProcessingActivity | None:
        return self.db.scalars(
            select(ProcessingActivity)
            .join(ActivitySystem, ActivitySystem.activity_id == ProcessingActivity.id)
            .where(ActivitySystem.system_id == system_id)
            .order_by(ProcessingActivity.created_at)
        ).first()

    def versions(self, activity_id: uuid.UUID) -> list[ActivityVersion]:
        return list(
            self.db.scalars(
                select(ActivityVersion)
                .where(ActivityVersion.activity_id == activity_id)
                .order_by(ActivityVersion.version)
            )
        )

    def version(self, activity_id: uuid.UUID, number: int) -> ActivityVersion | None:
        return self.db.scalars(
            select(ActivityVersion).where(
                ActivityVersion.activity_id == activity_id, ActivityVersion.version == number
            )
        ).first()

    def missing_fields(self, activity: ProcessingActivity) -> list[str]:
        latest = self.version(activity.id, activity.current_version)
        special = (latest.snapshot.get("special_categories") if latest else None) or []
        return completeness(snapshot_of(activity), list(special))

    # -- generate and edit -------------------------------------------------------------------

    def generate(self, system: System, draft: Draft, user_id: uuid.UUID | None) -> GenerateResult:
        """Create the record of a system, or refresh it from new evidence. Fields a person edited
        are kept; a changed record becomes a new version."""
        activity = self.for_system(system.id)
        fields = dict(draft.fields)
        owner = uuid.UUID(fields["owner_user_id"]) if fields.get("owner_user_id") else None
        if activity is None:
            activity = ProcessingActivity(
                id=uuid.uuid4(), name=str(fields["name"]), owner_user_id=owner
            )
            self._apply(activity, fields, draft.citations)
            self.db.add(activity)
            self.db.flush()
            self.db.add(ActivitySystem(activity_id=activity.id, system_id=system.id))
            self._store_version(
                activity, draft.special_categories, "Generated from evidence", user_id
            )
            return GenerateResult(activity, True, True, 1)

        manual = {
            f
            for f, refs in (activity.citations or {}).items()
            if any(r.get("kind") == "manual" for r in refs)
        }
        for name in manual:  # a person's edit beats regeneration
            if name in EDITABLE:
                fields[name] = _current_value(activity, name)
        citations = {
            k: ([*activity.citations[k]] if k in manual else v) for k, v in draft.citations.items()
        }
        before = snapshot_of(activity)
        self._apply(activity, fields, citations)
        after = snapshot_of(activity)
        changes = diff_snapshots(before, after)
        if not changes:
            activity.citations = citations  # same content, refreshed evidence references
            return GenerateResult(activity, False, False, activity.current_version)
        activity.current_version += 1
        if activity.status in (
            ActivityStatus.APPROVED,
            ActivityStatus.PUBLISHED,
            ActivityStatus.AWAITING_REVIEW,
        ):
            activity.status = ActivityStatus.DRAFT  # changed since it was reviewed
        self._store_version(
            activity, draft.special_categories, f"Regenerated. {summarize(changes)}", user_id
        )
        return GenerateResult(activity, False, True, activity.current_version)

    def edit(
        self, activity: ProcessingActivity, changes: dict[str, Any], user_id: uuid.UUID
    ) -> int:
        unknown = set(changes) - set(EDITABLE)
        if unknown:
            raise WorkflowError(f"Fields that cannot be edited: {sorted(unknown)}")
        before = snapshot_of(activity)
        citations = {k: list(v) for k, v in (activity.citations or {}).items()}
        for name, value in changes.items():
            _set_value(activity, name, value)
            mark = {"kind": "manual", "id": str(user_id), "detail": "edited by a person"}
            citations[name] = [r for r in citations.get(name, []) if r.get("kind") != "manual"] + [
                mark
            ]
        activity.citations = citations
        changed = diff_snapshots(before, snapshot_of(activity))
        if not changed:
            return activity.current_version
        activity.current_version += 1
        if activity.status is not ActivityStatus.ARCHIVED:
            activity.status = ActivityStatus.DRAFT
        latest = self.version(activity.id, activity.current_version - 1)
        special = (latest.snapshot.get("special_categories") if latest else None) or []
        self._store_version(activity, list(special), f"Edited. {summarize(changed)}", user_id)
        return activity.current_version

    # -- workflow ----------------------------------------------------------------------------

    def submit(self, activity: ProcessingActivity, user_id: uuid.UUID) -> Approval:
        if activity.status is not ActivityStatus.DRAFT:
            raise WorkflowError(
                f"Only a draft can be submitted (this one is {activity.status.value})"
            )
        missing = self.missing_fields(activity)
        if missing:
            raise WorkflowError("The record is incomplete", missing)
        activity.status = ActivityStatus.AWAITING_REVIEW
        approval = Approval(entity_type=ENTITY, entity_id=activity.id, requested_by=user_id)
        self.db.add(approval)
        self._system_state(activity, JobState.AWAITING_REVIEW)
        self.db.flush()
        return approval

    def decide(
        self, activity: ProcessingActivity, user_id: uuid.UUID, approve: bool, note: str | None
    ) -> Approval:
        if activity.status is not ActivityStatus.AWAITING_REVIEW:
            raise WorkflowError("Only a record that is awaiting review can be decided")
        approval = self.db.scalars(
            select(Approval)
            .where(
                Approval.entity_type == ENTITY,
                Approval.entity_id == activity.id,
                Approval.status == ApprovalStatus.PENDING,
            )
            .order_by(Approval.created_at.desc())
        ).first()
        if approval is None:
            raise WorkflowError("There is no pending review request")
        if approval.requested_by == user_id:
            raise WorkflowError("The person who submitted a record cannot approve it")
        approval.status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
        approval.decided_by, approval.decided_at, approval.decision_note = (
            user_id,
            datetime.now(UTC),
            note,
        )
        if approve:
            activity.status = ActivityStatus.APPROVED
            version = self.version(activity.id, activity.current_version)
            if version is not None:
                version.approved_by = user_id
            self._system_state(activity, JobState.APPROVED)
        else:
            activity.status = ActivityStatus.DRAFT
            self._system_state(activity, JobState.DRAFTED)
        self.db.flush()
        return approval

    def publish(self, activity: ProcessingActivity) -> None:
        if activity.status is not ActivityStatus.APPROVED:
            raise WorkflowError("Only an approved record can be published")
        activity.status = ActivityStatus.PUBLISHED
        self._system_state(activity, JobState.PUBLISHED)

    # -- internals ---------------------------------------------------------------------------

    def _apply(
        self, activity: ProcessingActivity, fields: dict[str, Any], citations: dict[str, Any]
    ) -> None:
        activity.name = str(fields["name"])
        activity.purposes = list(fields.get("purposes") or [])
        activity.data_subjects = list(fields.get("data_subjects") or [])
        activity.data_categories = list(fields.get("data_categories") or [])
        activity.recipients = list(fields.get("recipients") or [])
        activity.transfers = list(fields.get("transfers") or [])
        activity.retention = fields.get("retention")
        activity.security_measures = fields.get("security_measures")
        activity.lawful_basis = fields.get("lawful_basis")
        activity.special_category_condition = fields.get("special_category_condition")
        due = fields.get("next_review_date")
        activity.next_review_date = date.fromisoformat(due) if isinstance(due, str) else due
        if fields.get("owner_user_id"):
            activity.owner_user_id = uuid.UUID(str(fields["owner_user_id"]))
        activity.citations = citations

    def _store_version(
        self,
        activity: ProcessingActivity,
        special: list[str],
        summary: str,
        user_id: uuid.UUID | None,
    ) -> None:
        self.db.add(
            ActivityVersion(
                activity_id=activity.id,
                version=activity.current_version,
                snapshot=snapshot_of(activity, special),
                change_summary=summary[:2000],
                created_by=user_id,
            )
        )
        self._system_state(activity, JobState.DRAFTED, only_before=True)
        self.db.flush()

    def _system_state(
        self, activity: ProcessingActivity, state: JobState, only_before: bool = False
    ) -> None:
        for link in self.db.scalars(
            select(ActivitySystem).where(ActivitySystem.activity_id == activity.id)
        ):
            system = self.db.get(System, link.system_id)
            if system is None:
                continue
            if only_before and system.status not in (
                JobState.CLASSIFIED,
                JobState.FUSED,
                JobState.DRAFTED,
            ):
                continue
            system.status = state


def _current_value(activity: ProcessingActivity, name: str) -> Any:
    value = getattr(activity, name)
    return value.isoformat() if isinstance(value, date) else value


def _set_value(activity: ProcessingActivity, name: str, value: Any) -> None:
    if name == "next_review_date":
        value = date.fromisoformat(value) if isinstance(value, str) and value else None
    setattr(activity, name, value)


__all__ = ["ActivityService", "GenerateResult", "SNAPSHOT_FIELDS", "WorkflowError"]
