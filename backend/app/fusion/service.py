"""Run the fusion rules for a system, put the ambiguous conflicts to the model, and keep the
findings table in step with the result."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import FindingSeverity, FindingStatus, JobState
from app.db.models import Finding, System
from app.fusion.loader import FactsLoader
from app.fusion.rules import FINDING_TYPES, Ambiguity, RawFinding, run_rules
from app.knowledge.retrieval import Passage
from app.llm.errors import LLMError
from app.llm.router import LLMRouter
from app.llm.tasks import Scope, adjudicate_conflict

KEY_PREFIX = "fusion"
KEPT_STATUSES = (FindingStatus.ACKNOWLEDGED, FindingStatus.DISMISSED)


@dataclass
class FusionSummary:
    findings_open: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    adjudicated: int = 0
    adjudication_pending: int = 0
    tokens_used: int = 0
    status: str = ""


class FusionService:
    def __init__(
        self,
        db: Session,
        loader: FactsLoader,
        router: LLMRouter | None,
        org_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
    ) -> None:
        self.db = db
        self.loader = loader
        self.router = router
        self.org_id = org_id
        self.user_id = user_id

    def run(self, system: System) -> FusionSummary:
        facts = self.loader.load(system)
        output = run_rules(facts)
        summary = FusionSummary()
        wanted: dict[str, RawFinding] = {f.key: f for f in output.findings}
        for ambiguity in output.ambiguities:
            resolved = self._adjudicate(system, ambiguity, summary)
            wanted[resolved.key] = resolved
        self._sync(system, wanted)
        summary.findings_open = len(wanted)
        for finding in wanted.values():
            summary.by_type[finding.type] = summary.by_type.get(finding.type, 0) + 1
        if system.status in (JobState.CLASSIFIED, JobState.FUSED):
            system.status = JobState.FUSED
        summary.status = system.status.value
        return summary

    # -- model assisted conflicts ------------------------------------------------------------

    def _adjudicate(
        self, system: System, ambiguity: Ambiguity, summary: FusionSummary
    ) -> RawFinding:
        review = RawFinding(
            "retention_review", "low", ambiguity.subject,
            f"Review: {ambiguity.statement}",
            ambiguity.detail + " The rules cannot settle this; a person should decide.",
            "Decide whether the company limit applies and record the decision.",
            ambiguity.finding.refs,
        )  # fmt: skip
        if self.router is None:
            summary.adjudication_pending += 1
            return review
        passages = [
            Passage(uuid.UUID(pid), "document", f"doc:{pid}", "Company policy", text, 0.0)
            for pid, text in ambiguity.passages
        ]
        try:
            verdict, result = adjudicate_conflict(
                self.router,
                Scope(self.org_id, self.user_id, uuid.UUID(str(system.id))),
                conflict_type=ambiguity.type,
                statement=ambiguity.statement,
                detail=ambiguity.detail,
                passages=passages,
            )
        except LLMError:
            summary.adjudication_pending += 1  # no provider or no budget: keep it for review
            return review
        summary.adjudicated += 1
        summary.tokens_used += result.tokens
        note = f" Assessment: {verdict.explanation}"
        if verdict.verdict == "contradicts_policy":
            confirmed = ambiguity.finding
            confirmed.description += note
            return confirmed
        if verdict.verdict == "supported_by_policy":
            return RawFinding(
                "retention_review", "low", ambiguity.subject,
                f"Reviewed by assistant: {ambiguity.statement}",
                ambiguity.detail + note + " No conflict found; confirm and dismiss.",
                "Confirm the assessment and dismiss this item.", ambiguity.finding.refs,
            )  # fmt: skip
        review.description += note
        return review

    # -- findings table ----------------------------------------------------------------------

    def _sync(self, system: System, wanted: dict[str, RawFinding]) -> None:
        by_key = {f"{KEY_PREFIX}:{system.id}:{key}": f for key, f in wanted.items()}
        existing = {
            f.dedupe_key: f
            for f in self.db.scalars(
                select(Finding).where(
                    Finding.system_id == system.id, Finding.type.in_(FINDING_TYPES)
                )
            )
            if f.dedupe_key and f.dedupe_key.startswith(f"{KEY_PREFIX}:")
        }
        for key, raw in by_key.items():
            row = existing.get(key)
            refs: list[Any] = [r.as_dict() for r in raw.refs]
            if row is None:
                self.db.add(
                    Finding(
                        system_id=system.id, type=raw.type,
                        severity=FindingSeverity(raw.severity), title=raw.title[:300],
                        description=raw.description, suggested_fix=raw.suggested_fix,
                        evidence_refs=refs, dedupe_key=key,
                    )
                )  # fmt: skip
                continue
            row.title, row.description = raw.title[:300], raw.description
            row.suggested_fix, row.evidence_refs = raw.suggested_fix, refs
            row.type, row.severity = raw.type, FindingSeverity(raw.severity)
            if row.status is FindingStatus.RESOLVED:
                row.status, row.resolved_at = FindingStatus.OPEN, None
        for key, row in existing.items():
            if key not in by_key and row.status in (FindingStatus.OPEN, *KEPT_STATUSES):
                row.status, row.resolved_at = FindingStatus.RESOLVED, datetime.now(UTC)
        self.db.flush()
