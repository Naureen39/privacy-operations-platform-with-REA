"""Compliance snapshot of one organisation for one day, rebuilt from timestamps so a past day gives
the figures it would have had then (findings opened and resolved, approvals and their dates, the
review date on the version in force, requests received and answered)."""

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.billing.usage import day_end
from app.db.enums import ActivityStatus, ApprovalStatus, FindingStatus
from app.db.models import (
    AccessRequest,
    Approval,
    ComplianceDailyMetric,
    DataElement,
    DiscoveryEvidence,
    Dpia,
    Finding,
    ProcessingActivity,
)


def _utc(value: datetime | None) -> datetime | None:
    return value.astimezone(UTC) if value else None


def snapshot(db: Session, day: date) -> dict[str, Any]:
    end = day_end(day)

    # records: approved by the end of the day, and how many of those were past their review date
    approved_ids = {
        a.entity_id
        for a in db.scalars(
            select(Approval).where(
                Approval.entity_type == "processing_activity",
                Approval.status == ApprovalStatus.APPROVED,
                Approval.decided_at < end,
            )
        )
    }
    activities = list(
        db.scalars(
            select(ProcessingActivity).where(
                ProcessingActivity.created_at < end,
                ProcessingActivity.status != ActivityStatus.ARCHIVED,
            )
        )
    )
    approved = [a for a in activities if a.id in approved_ids]
    stale = 0
    for a in activities:
        due = db.execute(
            text(
                "SELECT snapshot->>'next_review_date' FROM activity_versions WHERE activity_id = :a AND created_at < :e ORDER BY version DESC LIMIT 1"
            ),
            {"a": a.id, "e": end},
        ).scalar()
        if due and date.fromisoformat(due) < day:
            stale += 1

    # findings open at the end of the day (a dismissed finding is not open)
    by_severity: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for f in db.scalars(
        select(Finding).where(Finding.created_at < end, Finding.status != FindingStatus.DISMISSED)
    ):
        resolved = _utc(f.resolved_at)
        if resolved is not None and resolved < end:
            continue
        by_severity[f.severity.value] = by_severity.get(f.severity.value, 0) + 1
        by_type[f.type] = by_type.get(f.type, 0) + 1

    # assessments by their state at the end of the day
    statuses: dict[str, int] = {}
    for dpia in db.scalars(select(Dpia).where(Dpia.created_at < end)):
        decided = db.scalars(
            select(Approval)
            .where(
                Approval.entity_type == "dpia",
                Approval.entity_id == dpia.id,
                Approval.created_at < end,
            )
            .order_by(Approval.created_at.desc())
        ).first()
        if decided is None:
            state = "draft"
        elif decided.decided_at is not None and _utc(decided.decided_at) < end:  # type: ignore[operator]
            state = "approved" if decided.status is ApprovalStatus.APPROVED else "rejected"
        else:
            state = "in_review"
        statuses[state] = statuses.get(state, 0) + 1

    # access requests open at the end of the day
    open_requests = overdue = 0
    for r in db.scalars(
        select(AccessRequest).where(
            AccessRequest.created_at < end, AccessRequest.received_date <= day
        )
    ):
        finished = _utc(r.responded_at) or _utc(r.closed_at)
        if finished is not None and finished < end:
            continue
        open_requests += 1
        overdue += int(r.deadline_date < day)

    confidence = db.scalar(
        select(func.avg(DataElement.confidence)).where(
            DataElement.created_at < end, DataElement.confidence.is_not(None)
        )
    )
    rea_ms = db.scalar(
        select(func.avg(DiscoveryEvidence.duration_ms)).where(
            DiscoveryEvidence.created_at < end, DiscoveryEvidence.extractor == "rea"
        )
    )
    return {
        "approved_records": len(approved),
        "stale_records": stale,
        "open_findings": {
            "total": sum(by_severity.values()),
            "by_severity": by_severity,
            "by_type": by_type,
        },
        "assessments_by_status": statuses,
        "requests_open": open_requests,
        "requests_overdue": overdue,
        "discovery_confidence_avg": round(float(confidence), 3) if confidence is not None else None,
        "rea_run_duration_ms_avg": int(rea_ms) if rea_ms is not None else None,
    }


def store(db: Session, day: date, simulated: bool = False) -> ComplianceDailyMetric:
    values = snapshot(db, day)
    org_id = db.info["tenant_context"].org_id
    stmt = pg_insert(ComplianceDailyMetric).values(
        org_id=org_id, metric_date=day, is_simulated=simulated, **values
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["org_id", "metric_date"], set_={**values, "is_simulated": simulated}
    )
    db.execute(stmt)
    db.flush()
    row = db.scalars(
        select(ComplianceDailyMetric).where(ComplianceDailyMetric.metric_date == day)
    ).one()
    db.refresh(row)
    return row
