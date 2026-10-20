"""Discovery run: extract facts from a system's evidence and store them with their provenance.

Every stored fact points at the `discovery_evidence` row of the extractor run that produced it
(raw output, command, REA version, duration). Facts found by several evidence items are merged
into one row whose context lists every row that supports it.

Classification (Phase 5) fills in category, special category and confidence later. A completed
run leaves the system in DISCOVERING: the next state, CLASSIFIED, belongs to that step.
"""

import hashlib
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select

from app.db.enums import EvidenceKind, Extractor, JobState, ReviewStatus
from app.db.models import (
    DataElement,
    DiscoveryEvidence,
    DiscoveryRun,
    EvidenceItem,
    Recipient,
    System,
    Technology,
)
from app.db.session import TenantSession
from app.discovery.candidates import (
    ElementCandidate,
    Extraction,
    RecipientCandidate,
    TechnologyCandidate,
)
from app.discovery.executor import SUPPORTED_KINDS, Executor, raw_summary
from app.services.evidence_store import EvidenceStore

# HAR first: its first request identifies the system's own host, which the other kinds exclude.
KIND_ORDER = {
    EvidenceKind.HAR: 0,
    EvidenceKind.WEBSITE: 1,
    EvidenceKind.JAVASCRIPT_BUNDLE: 2,
    EvidenceKind.SQLITE_SNAPSHOT: 3,
}


@dataclass
class _Pending:
    """A fact candidate together with the evidence row that supports it."""

    evidence_ids: list[uuid.UUID] = field(default_factory=list)
    extractors: list[str] = field(default_factory=list)
    item_ids: list[uuid.UUID] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    candidate: Any = None

    def primary_evidence_id(self) -> uuid.UUID:
        """REA is the primary extractor: prefer its row when several rows support the fact."""
        for evidence_id, extractor in zip(self.evidence_ids, self.extractors, strict=True):
            if extractor == Extractor.REA.value:
                return evidence_id
        return self.evidence_ids[0]


def _own_host(extraction: Extraction) -> str | None:
    for note in extraction.notes:
        if note.startswith("own_host=") and note != "own_host=None":
            return note.split("=", 1)[1]
    return None


class DiscoveryService:
    def __init__(self, db: TenantSession, store: EvidenceStore, executor: Executor) -> None:
        self.db = db
        self.store = store
        self.executor = executor

    # ------------------------------------------------------------------------------------------
    def run(self, system: System, user_id: uuid.UUID | None) -> DiscoveryRun:
        run = DiscoveryRun(system_id=system.id, state=JobState.DISCOVERING, created_by=user_id)
        self.db.add(run)
        system.status = JobState.DISCOVERING
        self.db.flush()

        items = [
            item
            for item in self.db.scalars(
                select(EvidenceItem)
                .where(EvidenceItem.system_id == system.id)
                .order_by(EvidenceItem.created_at)
            )
            if item.kind in SUPPORTED_KINDS
        ]
        items.sort(key=lambda i: (KIND_ORDER[i.kind], i.created_at))
        if not items:
            return self._fail(
                system, run, "no evidence of a supported kind is attached to this system"
            )

        elements: dict[tuple[str, str, str], _Pending] = {}
        recipients: dict[str, _Pending] = {}
        technologies: dict[tuple[str, str], _Pending] = {}
        item_reports: list[dict[str, Any]] = []
        own_host: str | None = None
        extractor_mix: dict[str, int] = defaultdict(int)
        any_success = False

        for item in items:
            outcomes = self._extract(item, own_host)
            report: dict[str, Any] = {
                "evidence_item_id": str(item.id),
                "kind": item.kind.value,
                "filename": item.filename,
                "runs": [],
            }
            primary: Extractor | None = None
            for extraction in outcomes:
                row = self._save_evidence(run, item, extraction)
                report["runs"].append(
                    {**raw_summary(extraction), "discovery_evidence_id": str(row.id)}
                )
                if extraction.status != "ok":
                    continue
                any_success = True
                extractor_mix[extraction.extractor.value] += 1
                primary = primary if primary is Extractor.REA else extraction.extractor
                own_host = own_host or _own_host(extraction)
                self._collect(item, row, extraction, elements, recipients, technologies)
            if primary is not None:
                item.extractor = primary
            item_reports.append(report)

        if not any_success:
            run.summary = {"items": item_reports}
            return self._fail(
                system,
                run,
                "every extractor failed; see the discovery evidence rows",
                keep_summary=True,
            )

        self._store_elements(system, elements)
        self._store_recipients(system, recipients)
        self._store_technologies(system, technologies)
        system.last_discovery_at = datetime.now(UTC)
        run.finished_at = datetime.now(UTC)
        run.summary = {
            "status": "completed",
            "own_host": own_host,
            "items": item_reports,
            "data_elements": len(elements),
            "recipients": len(recipients),
            "technologies": len(technologies),
            "extractor_mix": dict(extractor_mix),
        }
        self.db.flush()
        return run

    # ------------------------------------------------------------------------------------------
    def _fail(
        self, system: System, run: DiscoveryRun, message: str, keep_summary: bool = False
    ) -> DiscoveryRun:
        run.state = JobState.FAILED
        run.error = message
        run.finished_at = datetime.now(UTC)
        if not keep_summary:
            run.summary = {"status": "failed"}
        system.status = JobState.FAILED
        self.db.flush()
        return run

    def _extract(self, item: EvidenceItem, own_host: str | None) -> list[Extraction]:
        if not item.encrypted:  # a registered website URL: only the browser runner can read it
            return (
                self.executor.observe_url(item.storage_path, own_host)
                if item.kind is EvidenceKind.WEBSITE
                else []
            )
        try:
            data = self.store.read(item.storage_path, item.id)
        except Exception as exc:  # missing or tampered file: report it, do not stop the run
            return [
                self.executor._failed(item.kind, Extractor.FALLBACK, "read stored evidence", exc)
            ]  # noqa: SLF001
        if hashlib.sha256(data).hexdigest() != item.checksum_sha256:
            return [
                self.executor._failed(
                    item.kind,
                    Extractor.FALLBACK,
                    "verify checksum",
                    ValueError("stored evidence does not match its recorded checksum"),
                )
            ]  # noqa: SLF001
        return self.executor.process(item.kind, item.filename, data, own_host)

    def _save_evidence(
        self, run: DiscoveryRun, item: EvidenceItem, extraction: Extraction
    ) -> DiscoveryEvidence:
        row = DiscoveryEvidence(
            run_id=run.id,
            evidence_item_id=item.id,
            extractor=extraction.extractor,
            command=extraction.command,
            rea_version=extraction.rea_version,
            raw_output=extraction.raw_output,
            raw_sha256=extraction.raw_sha256,
            raw_truncated=extraction.raw_truncated,
            duration_ms=extraction.duration_ms,
            status=extraction.status,
            error=extraction.error,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def _collect(
        self,
        item: EvidenceItem,
        row: DiscoveryEvidence,
        extraction: Extraction,
        elements: dict[tuple[str, str, str], _Pending],
        recipients: dict[str, _Pending],
        technologies: dict[tuple[str, str], _Pending],
    ) -> None:
        def attach(pending: _Pending, candidate: Any) -> None:
            if row.id not in pending.evidence_ids:
                pending.evidence_ids.append(row.id)
                pending.extractors.append(extraction.extractor.value)
            if item.id not in pending.item_ids:
                pending.item_ids.append(item.id)
            if item.kind.value not in pending.kinds:
                pending.kinds.append(item.kind.value)
            if pending.candidate is None:
                pending.candidate = candidate

        for candidate in extraction.elements:
            attach(
                elements.setdefault(
                    (candidate.name, candidate.path, candidate.location_kind), _Pending()
                ),
                candidate,
            )
        for recipient in extraction.recipients:
            pending = recipients.setdefault(recipient.host, _Pending())
            attach(pending, recipient)
            if pending.candidate is not recipient:  # merge how it was observed
                via = set(pending.candidate.context.get("observed_via", [])) | set(
                    recipient.context.get("observed_via", [])
                )
                pending.candidate.context["observed_via"] = sorted(via)
                for key in ("urls", "parameters", "methods"):
                    merged = sorted(
                        set(pending.candidate.context.get(key, []))
                        | set(recipient.context.get(key, []))
                    )
                    if merged:
                        pending.candidate.context[key] = merged[:50]
        for technology in extraction.technologies:
            attach(
                technologies.setdefault((technology.kind, technology.name), _Pending()), technology
            )

    # ------------------------------------------------------------------------------------------
    def _store_elements(self, system: System, found: dict[tuple[str, str, str], _Pending]) -> None:
        existing = {
            (e.name, e.path or "", (e.context or {}).get("location_kind", "")): e
            for e in self.db.scalars(select(DataElement).where(DataElement.system_id == system.id))
        }
        keep: set[uuid.UUID] = set()
        for (name, path, kind), pending in found.items():
            candidate: ElementCandidate = pending.candidate
            context = {
                **candidate.context,
                "location_kind": candidate.location_kind,
                "evidence_item_ids": [str(i) for i in pending.item_ids],
                "discovery_evidence_ids": [str(i) for i in pending.evidence_ids],
            }
            row = existing.get((name, path, kind))
            if row is None:
                row = DataElement(system_id=system.id, name=name, path=path)
                self.db.add(row)
            row.data_type = candidate.data_type
            row.pattern_class = candidate.pattern_class
            row.context = context
            row.source_kind = pending.kinds[0]
            row.evidence_id = pending.primary_evidence_id()
            self.db.flush()
            keep.add(row.id)
        # Candidates that disappeared are dropped unless a person already reviewed them.
        for row in existing.values():
            if row.id not in keep and row.review_status is ReviewStatus.PENDING:
                self.db.delete(row)

    def _store_recipients(self, system: System, found: dict[str, _Pending]) -> None:
        existing = {
            r.domain: r
            for r in self.db.scalars(select(Recipient).where(Recipient.system_id == system.id))
        }
        for host, pending in found.items():
            candidate: RecipientCandidate = pending.candidate
            context = {
                **candidate.context,
                "evidence_item_ids": [str(i) for i in pending.item_ids],
                "discovery_evidence_ids": [str(i) for i in pending.evidence_ids],
                "evidence_kinds": pending.kinds,
            }
            row = existing.get(host)
            if row is None:
                row = Recipient(system_id=system.id, domain=host)
                self.db.add(row)
            row.context = context
            row.evidence_id = pending.primary_evidence_id()
        for host, row in existing.items():
            if (
                host not in found and not row.vendor
            ):  # vendor resolution (Phase 5) marks a reviewed row
                self.db.delete(row)
        self.db.flush()

    def _store_technologies(self, system: System, found: dict[tuple[str, str], _Pending]) -> None:
        self.db.execute(delete(Technology).where(Technology.system_id == system.id))
        for (kind, name), pending in found.items():
            candidate: TechnologyCandidate = pending.candidate
            self.db.add(
                Technology(
                    system_id=system.id,
                    name=name,
                    kind=kind,
                    version=candidate.version,
                    evidence_id=pending.primary_evidence_id(),
                    context={
                        **candidate.context,
                        "discovery_evidence_ids": [str(i) for i in pending.evidence_ids],
                    },
                )
            )
        self.db.flush()
