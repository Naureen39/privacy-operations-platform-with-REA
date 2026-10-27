"""A simulated year of compliance activity for the demonstration organisation: findings opened and
closed, records written, reviewed and approved, assessments, and access requests answered in
realistic times. Rows carry back dated timestamps; `compliance.store` then rebuilds a snapshot for
every day from them, so the history is derived exactly as live data would be. Deterministic for a
given seed. Run inside the organisation's tenant session."""

import hashlib
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.analytics import compliance
from app.db.enums import (
    ActivityStatus,
    ApprovalStatus,
    DpiaStatus,
    FindingSeverity,
    FindingStatus,
    RequestStatus,
)
from app.db.models import (
    AccessRequest,
    ActivityVersion,
    Approval,
    ComplianceDailyMetric,
    Dpia,
    Finding,
    ProcessingActivity,
)

FINDING_TYPES = (
    ("third_country_no_safeguard", 0.25),
    ("missing_agreement", 0.25),
    ("undeclared_recipient", 0.2),
    ("retention_mismatch", 0.15),
    ("special_category_unflagged", 0.15),
)
SEVERITY_WEIGHTS = (
    (FindingSeverity.LOW, 0.3),
    (FindingSeverity.MEDIUM, 0.4),
    (FindingSeverity.HIGH, 0.22),
    (FindingSeverity.CRITICAL, 0.08),
)
ACTIVITY_NAMES = (
    "Payroll processing", "Customer support", "Newsletter marketing", "Recruitment",
    "Website analytics", "Billing and invoicing", "CCTV at premises", "Customer loyalty programme",
    "Vendor management", "Employee onboarding", "Occupational health", "Event registration",
    "Fraud screening", "Training records",
)  # fmt: skip


@dataclass
class ComplianceSeedSummary:
    activities: int = 0
    findings: int = 0
    assessments: int = 0
    requests: int = 0
    snapshots: int = 0


def _at(day: date, rng: random.Random) -> datetime:
    return datetime.combine(day, time(rng.randint(8, 17), rng.randint(0, 59)), tzinfo=UTC)


def _pick(rng: random.Random, options: tuple[tuple[object, float], ...]) -> object:
    return rng.choices([o[0] for o in options], weights=[o[1] for o in options])[0]


def reset(db: Session) -> None:
    """Remove what an earlier run wrote (its rows are marked by the `seed:` prefix or the flag)."""
    db.execute(delete(ComplianceDailyMetric))
    db.execute(delete(AccessRequest).where(AccessRequest.reference.like("SIM-%")))
    db.execute(delete(Finding).where(Finding.dedupe_key.like("seed:%")))
    simulated = [
        a.id for a in db.query(ProcessingActivity).filter(ProcessingActivity.name.like("[Sim] %"))
    ]
    if simulated:
        db.execute(delete(Dpia).where(Dpia.activity_id.in_(simulated)))
        db.execute(delete(Approval).where(Approval.entity_id.in_(simulated)))
        db.execute(delete(ActivityVersion).where(ActivityVersion.activity_id.in_(simulated)))
        db.execute(delete(ProcessingActivity).where(ProcessingActivity.id.in_(simulated)))
    db.flush()


def seed_compliance_history(
    db: Session, *, seed: int = 42, as_of: date, months: int = 12
) -> ComplianceSeedSummary:
    rng = random.Random(seed)
    start = as_of - timedelta(days=round(months * 30.4))
    summary = ComplianceSeedSummary()
    span = (as_of - start).days

    # records: written over the first three quarters, approved within days, reviewed again later
    for i, name in enumerate(ACTIVITY_NAMES):
        created = start + timedelta(days=round(span * 0.75 * i / len(ACTIVITY_NAMES)))
        due = created + timedelta(days=rng.randint(150, 330))
        activity = ProcessingActivity(
            name=f"[Sim] {name}", status=ActivityStatus.APPROVED, current_version=1,
            next_review_date=due, created_at=_at(created, rng), updated_at=_at(created, rng),
        )  # fmt: skip
        db.add(activity)
        db.flush()
        approved_on = created + timedelta(days=rng.randint(1, 18))
        db.add(
            ActivityVersion(
                activity_id=activity.id,
                version=1,
                snapshot={"next_review_date": due.isoformat()},
                change_summary="Initial record",
                created_at=_at(created, rng),
            )
        )
        db.add(
            Approval(
                entity_type="processing_activity", entity_id=activity.id,
                status=ApprovalStatus.APPROVED, created_at=_at(created, rng),
                decided_at=_at(approved_on, rng),
            )
        )  # fmt: skip
        # most records are reviewed again (a new version with a later review date) once due
        if due < as_of and rng.random() < 0.7:
            reviewed = due + timedelta(days=rng.randint(-10, 25))
            if reviewed < as_of:
                new_due = reviewed + timedelta(days=rng.randint(240, 365))
                db.add(
                    ActivityVersion(
                        activity_id=activity.id, version=2,
                        snapshot={"next_review_date": new_due.isoformat()},
                        change_summary="Periodic review", created_at=_at(reviewed, rng),
                    )
                )  # fmt: skip
                activity.current_version, activity.next_review_date = 2, new_due
        summary.activities += 1

        # about a third of the records need an assessment
        if rng.random() < 0.35:
            opened = approved_on + timedelta(days=rng.randint(2, 20))
            decided = opened + timedelta(days=rng.randint(6, 40))
            outcome = rng.random()
            dpia = Dpia(
                activity_id=activity.id,
                status=DpiaStatus.DRAFT if decided > as_of or outcome > 0.9 else DpiaStatus.APPROVED,
                criteria_met=rng.randint(2, 4), created_at=_at(opened, rng),
                updated_at=_at(min(decided, as_of), rng),
            )  # fmt: skip
            db.add(dpia)
            db.flush()
            if decided <= as_of and outcome <= 0.9:
                db.add(
                    Approval(
                        entity_type="dpia", entity_id=dpia.id, status=ApprovalStatus.APPROVED,
                        created_at=_at(opened + timedelta(days=3), rng), decided_at=_at(decided, rng),
                    )
                )  # fmt: skip
            summary.assessments += 1

    # findings: a few a week, most closed within a month, some still open
    day = start
    count = 0
    while day <= as_of:
        for _ in range(rng.choices([0, 1, 2, 3], weights=[3, 4, 2, 1])[0]):
            severity = _pick(rng, SEVERITY_WEIGHTS)
            kind = str(_pick(rng, FINDING_TYPES))
            lifetime = (
                rng.randint(3, 45)
                if severity in (FindingSeverity.LOW, FindingSeverity.MEDIUM)
                else rng.randint(2, 21)
            )
            closes = day + timedelta(days=lifetime)
            closed = closes <= as_of and rng.random() < 0.85
            count += 1
            db.add(
                Finding(
                    type=kind, severity=severity, title=f"{kind.replace('_', ' ').capitalize()} ({count})",
                    status=FindingStatus.RESOLVED if closed else FindingStatus.OPEN,
                    dedupe_key=f"seed:{count}", created_at=_at(day, rng), updated_at=_at(day, rng),
                    resolved_at=_at(closes, rng) if closed else None,
                )
            )  # fmt: skip
            summary.findings += 1
        day += timedelta(days=1)

    # access requests: answered in about 10 days on average, a few late, a few still open
    received = start + timedelta(days=5)
    number = 0
    while received <= as_of:
        number += 1
        deadline = received + timedelta(days=30)
        took = max(1, round(rng.lognormvariate(2.3, 0.5)))
        late = rng.random() < 0.06
        responded_on = (
            deadline + timedelta(days=rng.randint(1, 9))
            if late
            else received + timedelta(days=took)
        )
        answered = responded_on <= as_of
        db.add(
            AccessRequest(
                subject_hash=hashlib.sha256(f"sim-{seed}-{number}".encode()).hexdigest(),
                received_date=received, deadline_date=deadline,
                status=RequestStatus.CLOSED if answered else RequestStatus.SEARCHING,
                identifier_type="email", reference=f"SIM-{received.year}-{number:04d}",
                created_at=_at(received, rng), updated_at=_at(min(responded_on, as_of), rng),
                responded_at=_at(responded_on, rng) if answered else None,
                closed_at=_at(responded_on, rng) if answered else None,
            )
        )  # fmt: skip
        summary.requests += 1
        received += timedelta(days=rng.randint(6, 16))
    db.flush()

    day = start
    while day <= as_of:
        compliance.store(db, day, simulated=True)
        summary.snapshots += 1
        day += timedelta(days=1)
    return summary
