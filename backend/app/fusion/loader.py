"""Collect the facts of one system from the database and the evidence store."""

import json
import re
import uuid
from datetime import date
from pathlib import Path
from typing import Protocol

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.classify.engine import Classifier
from app.classify.features import ElementFeatures
from app.classify.knowledge import DEFAULT_DIR
from app.db.enums import DocumentType, EvidenceKind, ReviewStatus
from app.db.models import (
    DataElement,
    Document,
    DocumentChunk,
    EvidenceItem,
    Recipient,
    System,
)
from app.fusion.facts import (
    CompanyRules,
    ElementFact,
    PolicyFacts,
    Questionnaire,
    RecipientFact,
    Ref,
    SystemFacts,
)
from app.fusion.policy import extract_claims, parse_policy, retention_months
from app.services.evidence_store import EvidenceStore

_PROCESSOR_LINE = re.compile(
    r"Processor:\s*(?P<vendor>[^(.]+?)\s*(?:\([A-Za-z]{2}\))?\s*\.", re.IGNORECASE
)


class Categorizer(Protocol):
    def categories(self, phrases: list[str]) -> list[list[str]]:
        """For each phrase the categories it names: the decided one first, then close candidates."""
        ...


# A notice is free text: "an identifier of your computer" is a device identifier even though the
# classifier is not sure enough to decide. Candidates this close count as named by the notice.
CLOSE_CANDIDATE = 0.80


class ClassifierCategorizer:
    """Maps a phrase from a notice ("your date of birth") to a taxonomy category with the same
    rules and embeddings that classify discovered elements."""

    def __init__(self, classifier: Classifier) -> None:
        self.classifier = classifier

    def categories(self, phrases: list[str]) -> list[list[str]]:
        features = [
            ElementFeatures(
                name=_clean_phrase(p), location_kind="policy_text", source_kind="policy"
            )
            for p in phrases
        ]
        result = []
        for r in self.classifier.classify(features):
            decided = [r.decision.category] if r.decision.category else []
            close = [
                c
                for c, score in r.decision.candidates
                if score >= CLOSE_CANDIDATE and c not in decided
            ]
            result.append(decided + close)
        return result


def _clean_phrase(text: str) -> str:
    text = re.sub(r"\([^)]*\)", " ", text)  # "(stored only as a hash)"
    text = re.sub(r"\b(your|the|our|a|an|of)\b", " ", text, flags=re.IGNORECASE)
    return " ".join(text.split())


def load_adequacy(directory: Path | None = None) -> tuple[frozenset[str], frozenset[str]]:
    """Countries whose adequacy decision applies without a further check, and the EEA."""
    data = yaml.safe_load(
        ((directory or DEFAULT_DIR) / "adequacy_countries.yaml").read_text(encoding="utf-8")
    )
    adequate = frozenset(
        c["code"] for c in data["adequacy"] if not c.get("requires_certification_check")
    )
    return adequate, frozenset(data["eea"])


class FactsLoader:
    def __init__(
        self,
        db: Session,
        store: EvidenceStore,
        categorizer: Categorizer,
        org_id: uuid.UUID,
        as_of: date | None = None,
        knowledge_dir: Path | None = None,
    ) -> None:
        self.db = db
        self.store = store
        self.categorizer = categorizer
        self.org_id = org_id
        self.as_of = as_of or date.today()
        self.adequate, self.eea = load_adequacy(knowledge_dir)

    def load(self, system: System) -> SystemFacts:
        questionnaire = self._questionnaire(system)
        policy = self._policy(system)
        facts = SystemFacts(
            system_id=str(system.id),
            name=system.name,
            elements=self._elements(system),
            recipients=self._recipients(system),
            questionnaire=questionnaire,
            policy=policy,
            company=self._company_rules(),
            agreement_vendors=self._agreement_vendors(),
            adequate=self.adequate,
            eea=self.eea,
            as_of=self.as_of,
        )
        if policy is not None:
            self._categorize_policy(facts, policy)
        return facts

    # -- evidence ----------------------------------------------------------------------------

    def _latest(self, system: System, kind: EvidenceKind) -> EvidenceItem | None:
        return self.db.scalars(
            select(EvidenceItem)
            .where(EvidenceItem.system_id == system.id, EvidenceItem.kind == kind)
            .order_by(EvidenceItem.created_at.desc())
        ).first()

    def _questionnaire(self, system: System) -> Questionnaire | None:
        item = self._latest(system, EvidenceKind.QUESTIONNAIRE)
        if item is None:
            return None
        try:
            data = json.loads(self.store.read(item.storage_path, item.id).decode("utf-8-sig"))
        except (OSError, ValueError):
            return None
        answers = data.get("answers", data) if isinstance(data, dict) else {}
        return Questionnaire(answers, Ref("questionnaire", str(item.id), item.filename))

    def _policy(self, system: System) -> PolicyFacts | None:
        item = self._latest(system, EvidenceKind.PRIVACY_POLICY)
        if item is None or not item.filename.lower().endswith((".md", ".txt")):
            return None  # PDF and HTML notices are indexed for search but not parsed by the rules
        try:
            text = self.store.read(item.storage_path, item.id).decode("utf-8-sig")
        except (OSError, ValueError):
            return None
        return parse_policy(text, Ref("policy", str(item.id), item.filename))

    # -- discovered facts --------------------------------------------------------------------

    def _elements(self, system: System) -> list[ElementFact]:
        facts = []
        for e in self.db.scalars(select(DataElement).where(DataElement.system_id == system.id)):
            ctx = e.context or {}
            location = str(ctx.get("location_kind", ""))
            facts.append(
                ElementFact(
                    name=e.name,
                    category=e.category,
                    special=e.special_category,
                    location_kind=location,
                    table=ctx.get("table"),
                    pattern_class=e.pattern_class,
                    checked_by_default=bool(ctx.get("checked_by_default")),
                    input_type=ctx.get("input_type"),
                    record_months=ctx.get("record_months"),
                    confidence=float(e.confidence) if e.confidence is not None else None,
                    reviewed=e.review_status is not ReviewStatus.PENDING,
                    ref=Ref(
                        "discovery",
                        str(e.evidence_id) if e.evidence_id else None,
                        f"{location} {e.name}",
                    ),
                )
            )
        return facts

    def _recipients(self, system: System) -> list[RecipientFact]:
        return [
            RecipientFact(
                vendor=r.vendor,
                domain=r.domain,
                role=r.role.value,
                country=r.country,
                internal=bool((r.context or {}).get("internal")),
                ref=Ref(
                    "discovery",
                    str(r.evidence_id) if r.evidence_id else None,
                    f"recipient {r.domain}",
                ),
            )
            for r in self.db.scalars(select(Recipient).where(Recipient.system_id == system.id))
        ]

    # -- organisation wide documents ---------------------------------------------------------

    def _company_rules(self) -> CompanyRules | None:
        rows = self.db.execute(
            select(DocumentChunk, Document)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                Document.system_id.is_(None),
                Document.doc_type == DocumentType.POLICY,
                DocumentChunk.heading.ilike("%retention%"),
            )
            .order_by(Document.created_at, DocumentChunk.chunk_index)
        ).all()
        for chunk, document in rows:
            periods = retention_months(chunk.text)
            if periods:
                return CompanyRules(
                    min(periods), chunk.text[:300],
                    [(str(chunk.id), chunk.text)],
                    Ref("company_policy", str(document.id), f"{document.title}, {chunk.heading}"),
                )  # fmt: skip
        return None

    def _agreement_vendors(self) -> set[str]:
        vendors: set[str] = set()
        for (text,) in self.db.execute(
            select(DocumentChunk.text)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(Document.doc_type == DocumentType.VENDOR_AGREEMENT)
        ):
            match = _PROCESSOR_LINE.search(text)
            if match:
                vendors.add(match["vendor"].strip())
        return vendors

    # -- reading the notice with the classifier ----------------------------------------------

    def _categorize_policy(self, facts: SystemFacts, policy: PolicyFacts) -> None:
        claims = [c for c in extract_claims(policy) if c.kind == "negative_storage" and c.subject]
        phrases = [*policy.collected, *[c.subject or "" for c in claims]]
        categories = self.categorizer.categories(phrases)
        facts.policy_categories = {
            c for names in categories[: len(policy.collected)] for c in names
        }
        for claim, names in zip(claims, categories[len(policy.collected) :], strict=True):
            facts.claim_categories[claim.subject or ""] = names[0] if names else None
