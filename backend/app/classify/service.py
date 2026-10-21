"""Classification of a system's discovered facts, stored with the reasons for each decision.

Elements get a category, an Article 9 flag and a confidence (never from an LLM). Anything
special or near special is queued for review whatever its confidence, as are plausible
elements the thresholds could not decide and recipient hosts the registry does not know.
Reviewed elements are not overwritten.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.classify.engine import Classifier, ElementResult
from app.classify.features import ElementFeatures
from app.classify.knowledge import Knowledge
from app.classify.vendors import resolve_host
from app.db.enums import FindingSeverity, FindingStatus, JobState, RecipientRole, ReviewStatus
from app.db.models import DataElement, Finding, Recipient, System
from app.db.session import TenantSession

MANAGED_TYPES = (
    "special_category_review",
    "low_confidence_classification",
    "unknown_recipient_host",
)


@dataclass
class ClassificationSummary:
    elements: int = 0
    classified: int = 0
    unclassified: int = 0
    non_personal: int = 0
    reviewed_kept: int = 0
    special_strong: int = 0
    special_near: int = 0
    recipients: int = 0
    recipients_known: int = 0
    recipients_internal: int = 0
    recipients_unknown: int = 0
    findings_open: int = 0
    methods: dict[str, int] = field(default_factory=dict)
    thresholds_version: str = ""
    embedding_model: str = ""


class ClassificationService:
    def __init__(self, db: TenantSession, classifier: Classifier, knowledge: Knowledge) -> None:
        self.db = db
        self.classifier = classifier
        self.knowledge = knowledge

    def run(self, system: System) -> ClassificationSummary:
        summary = ClassificationSummary(
            thresholds_version=self.knowledge.thresholds.version,
            embedding_model=self.classifier.embedder.name,
        )
        wanted: dict[str, dict[str, Any]] = {}

        rows = list(
            self.db.scalars(
                select(DataElement)
                .where(DataElement.system_id == system.id)
                .order_by(DataElement.name, DataElement.path)
            )
        )
        features = [
            ElementFeatures.from_context(
                r.name,
                r.context or {},
                data_type=r.data_type,
                pattern_class=r.pattern_class,
                source_kind=r.source_kind,
            )
            for r in rows
        ]
        results = self.classifier.classify(features)
        for row, result in zip(rows, results, strict=True):
            summary.elements += 1
            if row.review_status is not ReviewStatus.PENDING:
                summary.reviewed_kept += 1
                continue
            self._apply(row, result, summary)
            self._queue_element_reviews(system, row, result, wanted)

        self._resolve_recipients(system, summary, wanted)
        self._sync_findings(system, wanted, summary)
        system.status = JobState.CLASSIFIED
        self.db.flush()
        return summary

    # ------------------------------------------------------------------------------------------
    def _apply(
        self, row: DataElement, result: ElementResult, summary: ClassificationSummary
    ) -> None:
        decision, special = result.decision, result.special
        row.category = decision.category
        row.confidence = Decimal(str(decision.confidence)) if decision.category else None
        row.special_category = bool(special and special.level == "strong")
        row.special_category_label = (
            special.label if special and special.level == "strong" else None
        )
        row.embedding = result.vector
        row.context = {
            **(row.context or {}),
            "classification": {
                "method": decision.method,
                "reasons": decision.reasons[:6],
                "candidates": [
                    {"category": c, "score": round(s, 3)} for c, s in decision.candidates
                ],
                "description": result.description,
                "special": (
                    {
                        "level": special.level,
                        "category": special.category_id,
                        "reason": special.reason,
                    }
                    if special
                    else None
                ),
                "needs_review": bool(special or decision.needs_review),
                "thresholds_version": self.knowledge.thresholds.version,
                "embedding_model": self.classifier.embedder.name,
            },
        }
        summary.methods[decision.method] = summary.methods.get(decision.method, 0) + 1
        if decision.category:
            summary.classified += 1
        elif decision.method == "non_personal":
            summary.non_personal += 1
        else:
            summary.unclassified += 1
        if special:
            if special.level == "strong":
                summary.special_strong += 1
            else:
                summary.special_near += 1

    def _queue_element_reviews(
        self,
        system: System,
        row: DataElement,
        result: ElementResult,
        wanted: dict[str, dict[str, Any]],
    ) -> None:
        refs = [
            {
                "data_element_id": str(row.id),
                "discovery_evidence_id": str(row.evidence_id) if row.evidence_id else None,
            }
        ]
        special = result.special
        if special:
            strong = special.level == "strong"
            wanted[f"classify:special:{system.id}:{row.id}"] = {
                "type": "special_category_review",
                "severity": FindingSeverity.HIGH if strong else FindingSeverity.MEDIUM,
                "title": f"Review {'special category data' if strong else 'data near a special category'}: {row.name}",
                "description": (
                    f"'{row.name}' ({row.path}) {'is' if strong else 'is close to'} {special.label} data under Article 9: {special.reason}. "
                    "Any such element needs a person's decision, whatever the classifier's confidence."
                ),
                "suggested_fix": "Confirm whether the element is special category data and record the Article 9 condition that applies.",
                "evidence_refs": refs,
            }
        elif result.decision.needs_review:
            candidates = ", ".join(f"{c} ({s:.2f})" for c, s in result.decision.candidates[:2])
            wanted[f"classify:low:{system.id}:{row.id}"] = {
                "type": "low_confidence_classification",
                "severity": FindingSeverity.LOW,
                "title": f"Classify data element: {row.name}",
                "description": f"'{row.name}' ({row.path}) looks like personal data but no category met the thresholds. Closest: {candidates}.",
                "suggested_fix": "Choose the category that applies, or mark the element as not personal data.",
                "evidence_refs": refs,
            }

    def _resolve_recipients(
        self, system: System, summary: ClassificationSummary, wanted: dict[str, dict[str, Any]]
    ) -> None:
        for recipient in self.db.scalars(
            select(Recipient).where(Recipient.system_id == system.id).order_by(Recipient.domain)
        ):
            summary.recipients += 1
            resolution = resolve_host(recipient.domain, self.knowledge)
            context = {
                **(recipient.context or {}),
                "vendor_resolution": {
                    "pattern": resolution.pattern,
                    "internal": resolution.internal,
                    "known": resolution.known,
                },
            }
            if resolution.internal:
                summary.recipients_internal += 1
                context["internal"] = True
                recipient.category = "internal"
                recipient.role = RecipientRole.CONTROLLER
            elif resolution.vendor:
                summary.recipients_known += 1
                if not recipient.vendor or (recipient.context or {}).get(
                    "vendor_resolution", {}
                ).get("pattern"):
                    recipient.vendor = resolution.vendor  # a vendor set by a person is kept
                    recipient.role = RecipientRole(resolution.role or "unknown")
                    recipient.country = resolution.country
                    recipient.category = resolution.category
            else:
                summary.recipients_unknown += 1
                if recipient.vendor is None:
                    wanted[f"classify:host:{system.id}:{recipient.domain}"] = {
                        "type": "unknown_recipient_host",
                        "severity": FindingSeverity.MEDIUM,
                        "title": f"Identify recipient: {recipient.domain}",
                        "description": f"Traffic or code references {recipient.domain}, which is not in the vendor registry. Its vendor, role and country are unknown.",
                        "suggested_fix": "Identify the vendor and add it to the registry, or confirm the host belongs to the organisation.",
                        "evidence_refs": [
                            {
                                "recipient_id": str(recipient.id),
                                "discovery_evidence_id": (
                                    str(recipient.evidence_id) if recipient.evidence_id else None
                                ),
                            }
                        ],
                    }
            recipient.context = context

    def _sync_findings(
        self, system: System, wanted: dict[str, dict[str, Any]], summary: ClassificationSummary
    ) -> None:
        existing = {
            f.dedupe_key: f
            for f in self.db.scalars(
                select(Finding).where(
                    Finding.system_id == system.id, Finding.type.in_(MANAGED_TYPES)
                )
            )
            if f.dedupe_key
        }
        for key, spec in wanted.items():
            finding = existing.get(key)
            if finding is None:
                self.db.add(
                    Finding(
                        system_id=system.id, type=spec["type"], severity=spec["severity"], title=spec["title"],
                        description=spec["description"], suggested_fix=spec["suggested_fix"],
                        evidence_refs=spec["evidence_refs"], dedupe_key=key,
                    )
                )  # fmt: skip
            elif finding.status in (FindingStatus.RESOLVED,):
                finding.status = FindingStatus.OPEN  # it applies again
                finding.resolved_at = None
        for key, finding in existing.items():
            if key not in wanted and finding.status is FindingStatus.OPEN:
                finding.status = FindingStatus.RESOLVED
                finding.resolved_at = datetime.now(UTC)
        self.db.flush()
        summary.findings_open = len(wanted)
