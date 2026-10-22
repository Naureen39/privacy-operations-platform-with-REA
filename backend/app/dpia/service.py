"""Screening and the assessment record: persistence, the risk register, completeness and review."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import ApprovalStatus, DpiaStatus
from app.db.models import (
    ActivitySystem,
    ActivityVersion,
    Approval,
    Dpia,
    DpiaRisk,
    DpiaScreening,
    ProcessingActivity,
    System,
)
from app.dpia import matrix
from app.dpia.screening import CriteriaSet, Scale, ScreeningInput, screen
from app.fusion.facts import Ref
from app.fusion.loader import FactsLoader

ENTITY = "dpia"
TEXT_SECTIONS = ("why we use", "how we handle", "who we are")


class DpiaWorkflowError(Exception):
    def __init__(self, message: str, missing: list[str] | None = None) -> None:
        super().__init__(message)
        self.missing = missing or []


@dataclass
class RiskInput:
    title: str
    description: str | None
    likelihood: int
    severity: int
    mitigation: str | None
    residual_likelihood: int | None
    residual_severity: int | None
    citation: str | None


def find_screening(db: Session, activity_id: uuid.UUID) -> DpiaScreening | None:
    return db.scalars(select(DpiaScreening).where(DpiaScreening.activity_id == activity_id)).first()


class ScreeningService:
    def __init__(self, db: Session, loader: FactsLoader, criteria: CriteriaSet) -> None:
        self.db = db
        self.loader = loader
        self.criteria = criteria

    def get(self, activity_id: uuid.UUID) -> DpiaScreening | None:
        return find_screening(self.db, activity_id)

    def run(
        self,
        system: System,
        activity: ProcessingActivity,
        scale: Scale | None,
        user_id: uuid.UUID | None,
    ) -> DpiaScreening:
        row = self.get(activity.id)
        stored = (row.inputs if row else {}) or {}
        merged = Scale(
            data_subjects_estimate=stored.get("data_subjects_estimate"),
            countries=stored.get("countries"),
            flags=list(stored.get("flags") or []),
        )
        if scale is not None:
            if scale.data_subjects_estimate is not None:
                merged.data_subjects_estimate = scale.data_subjects_estimate
            if scale.countries is not None:
                merged.countries = scale.countries
            if scale.flags:
                merged.flags = scale.flags
        result = screen(self.build_input(system, activity, merged), self.criteria)
        if row is None:
            row = DpiaScreening(activity_id=activity.id)
            self.db.add(row)
        row.criteria = [r.as_dict() for r in result.results]
        row.criteria_met, row.criteria_unknown = result.met, result.unknown
        row.threshold, row.required = result.threshold, result.required
        row.inputs, row.criteria_version = merged.as_dict(), self.criteria.version
        row.screened_by = user_id
        self.db.flush()
        return row

    def build_input(
        self, system: System, activity: ProcessingActivity, scale: Scale
    ) -> ScreeningInput:
        facts = self.loader.load(system)
        latest = self.db.scalars(
            select(ActivityVersion).where(
                ActivityVersion.activity_id == activity.id,
                ActivityVersion.version == activity.current_version,
            )
        ).first()
        special = list((latest.snapshot.get("special_categories") if latest else None) or [])
        extra: list[str] = []
        if facts.policy:
            extra += [
                s for h, s in facts.policy.sentences() if any(t in h.lower() for t in TEXT_SECTIONS)
            ]
            extra += facts.policy.collected
        extra += [r.purpose for r in facts.recipients if r.purpose and not r.internal]
        return ScreeningInput(
            name=activity.name,
            description=system.description or "",
            data_subjects=list(activity.data_subjects),
            purposes=list(activity.purposes),
            extra_text=extra,
            elements=facts.elements,
            recipients=facts.recipients,
            special_categories=special,
            categories=list(activity.data_categories),
            scale=scale,
            activity_ref=Ref("record", str(activity.id), "processing activity record"),
        )


class AssessmentService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # -- lookups -----------------------------------------------------------------------------

    def for_activity(self, activity_id: uuid.UUID) -> Dpia | None:
        return self.db.scalars(
            select(Dpia).where(Dpia.activity_id == activity_id).order_by(Dpia.created_at.desc())
        ).first()

    def risks(self, dpia_id: uuid.UUID) -> list[DpiaRisk]:
        return list(
            self.db.scalars(
                select(DpiaRisk).where(DpiaRisk.dpia_id == dpia_id).order_by(DpiaRisk.id)
            )
        )

    def systems_of(self, activity_id: uuid.UUID) -> list[System]:
        ids = self.db.scalars(
            select(ActivitySystem.system_id).where(ActivitySystem.activity_id == activity_id)
        )
        return [s for s in (self.db.get(System, i) for i in ids) if s is not None]

    # -- creation and editing ----------------------------------------------------------------

    def create(
        self,
        activity: ProcessingActivity,
        screening: DpiaScreening,
        user_id: uuid.UUID | None,
        reason: str | None,
    ) -> Dpia:
        open_one = self.for_activity(activity.id)
        if open_one is not None and open_one.status in (DpiaStatus.DRAFT, DpiaStatus.IN_REVIEW):
            raise DpiaWorkflowError("An assessment for this activity is already in progress")
        if not screening.required and not reason:
            raise DpiaWorkflowError(
                "Screening does not require an assessment; give a reason to start one anyway"
            )
        dpia = Dpia(
            activity_id=activity.id,
            created_by=user_id,
            criteria_met=screening.criteria_met,
            trigger_scores={
                "screening": {
                    "criteria": screening.criteria, "met": screening.criteria_met,
                    "threshold": screening.threshold, "required": screening.required,
                    "criteria_version": screening.criteria_version, "inputs": screening.inputs,
                },
                "started_anyway_reason": reason if not screening.required else None,
            },
        )  # fmt: skip
        self.db.add(dpia)
        self.db.flush()
        return dpia

    def set_texts(
        self, dpia: Dpia, description: str | None = None, necessity: str | None = None
    ) -> None:
        if description is not None:
            dpia.description = description
        if necessity is not None:
            dpia.necessity_proportionality = necessity
        self._reopen(dpia)

    def replace_risks(self, dpia: Dpia, items: list[RiskInput]) -> list[DpiaRisk]:
        for risk in self.risks(dpia.id):
            self.db.delete(risk)
        self.db.flush()
        rows = [self._risk_row(dpia, item) for item in items]
        self.db.add_all(rows)
        self.db.flush()
        self.refresh_residual(dpia)
        return rows

    def add_risk(self, dpia: Dpia, item: RiskInput) -> DpiaRisk:
        row = self._risk_row(dpia, item)
        self.db.add(row)
        self.db.flush()
        self._reopen(dpia)
        self.refresh_residual(dpia)
        return row

    def update_risk(self, dpia: Dpia, risk: DpiaRisk, changes: dict[str, Any]) -> DpiaRisk:
        for name, value in changes.items():
            setattr(risk, name, value)
        self.db.flush()
        self._reopen(dpia)
        self.refresh_residual(dpia)
        return risk

    def delete_risk(self, dpia: Dpia, risk: DpiaRisk) -> None:
        self.db.delete(risk)
        self.db.flush()
        self._reopen(dpia)
        self.refresh_residual(dpia)

    def refresh_residual(self, dpia: Dpia) -> None:
        """The overall residual risk is the highest band among the risks (the inherent band for a
        risk whose residual rating is not set yet)."""
        bands = [
            matrix.level(r.residual_likelihood or r.likelihood, r.residual_severity or r.severity)
            for r in self.risks(dpia.id)
        ]
        dpia.residual_risk = matrix.worst(bands)

    def _risk_row(self, dpia: Dpia, item: RiskInput) -> DpiaRisk:
        return DpiaRisk(
            dpia_id=dpia.id, title=item.title[:300], description=item.description,
            likelihood=item.likelihood, severity=item.severity, mitigation=item.mitigation,
            residual_likelihood=item.residual_likelihood, residual_severity=item.residual_severity,
            citation=(item.citation or None) and item.citation[:200],
        )  # fmt: skip

    def _reopen(self, dpia: Dpia) -> None:
        if dpia.status is DpiaStatus.REJECTED:
            dpia.status = DpiaStatus.DRAFT
        elif dpia.status in (DpiaStatus.IN_REVIEW, DpiaStatus.APPROVED):
            raise DpiaWorkflowError(
                f"A {dpia.status.value.replace('_', ' ')} assessment cannot be edited"
            )

    # -- completeness and review -------------------------------------------------------------

    def missing(self, dpia: Dpia, for_approval: bool = False) -> list[str]:
        gaps: list[str] = []
        if not (dpia.description or "").strip():
            gaps.append("description")
        if not (dpia.necessity_proportionality or "").strip():
            gaps.append("necessity_proportionality")
        risks = self.risks(dpia.id)
        if not risks:
            gaps.append("risks")
        for r in risks:
            label = f"risk:{r.title[:40]}"
            if not (r.mitigation or "").strip():
                gaps.append(f"{label}:mitigation")
            if not (r.citation or "").strip():
                gaps.append(f"{label}:citation")
            if r.residual_likelihood is None or r.residual_severity is None:
                gaps.append(f"{label}:residual_rating")
        if not dpia.residual_risk:
            gaps.append("residual_risk")
        if for_approval and not (dpia.officer_opinion or "").strip():
            gaps.append("officer_opinion")
        return gaps

    def submit(self, dpia: Dpia, user_id: uuid.UUID) -> Approval:
        if dpia.status is not DpiaStatus.DRAFT:
            raise DpiaWorkflowError(
                f"Only a draft can be submitted (this one is {dpia.status.value})"
            )
        gaps = self.missing(dpia)
        if gaps:
            raise DpiaWorkflowError("The assessment is incomplete", gaps)
        dpia.status = DpiaStatus.IN_REVIEW
        approval = Approval(entity_type=ENTITY, entity_id=dpia.id, requested_by=user_id)
        self.db.add(approval)
        self.db.flush()
        return approval

    def decide(self, dpia: Dpia, user_id: uuid.UUID, approve: bool, note: str | None) -> Approval:
        if dpia.status is not DpiaStatus.IN_REVIEW:
            raise DpiaWorkflowError("Only an assessment that is in review can be decided")
        if approve:
            gaps = self.missing(dpia, for_approval=True)
            if gaps:
                raise DpiaWorkflowError("The assessment is incomplete", gaps)
        approval = self.db.scalars(
            select(Approval)
            .where(
                Approval.entity_type == ENTITY,
                Approval.entity_id == dpia.id,
                Approval.status == ApprovalStatus.PENDING,
            )
            .order_by(Approval.created_at.desc())
        ).first()
        if approval is None:
            raise DpiaWorkflowError("There is no pending review request")
        if approval.requested_by == user_id:
            raise DpiaWorkflowError("The person who submitted an assessment cannot approve it")
        approval.status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
        approval.decided_by, approval.decided_at, approval.decision_note = (
            user_id,
            datetime.now(UTC),
            note,
        )
        dpia.status = DpiaStatus.APPROVED if approve else DpiaStatus.REJECTED
        self.db.flush()
        return approval
