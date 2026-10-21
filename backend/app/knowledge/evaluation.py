"""Gold set evaluation for retrieval: recall at k over hand written questions, with the pieces
needed to load the reference documents of the demonstration estate into a test organisation."""

import json
import statistics
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.classify.embedder import Embedder
from app.db.enums import DocumentType
from app.knowledge.ingest import DocumentIngestor
from app.knowledge.retrieval import Filters, HybridRetriever, Passage

DATASETS = Path(__file__).resolve().parents[3] / "datasets"
GOLD_FILE = DATASETS / "evaluation" / "retrieval_gold.json"


@dataclass(frozen=True)
class ReferenceDocument:
    path: str  # relative to the datasets folder, used as the source uri
    doc_type: DocumentType
    system_key: str | None


def reference_documents(datasets: Path = DATASETS) -> list[ReferenceDocument]:
    docs: list[ReferenceDocument] = []
    estate = json.loads((datasets / "estate" / "estate.json").read_text(encoding="utf-8"))
    for system in estate["systems"]:
        key = system["id"]
        docs.append(ReferenceDocument(f"estate/{key}/policy.md", DocumentType.POLICY, key))
        docs.append(
            ReferenceDocument(f"estate/{key}/questionnaire.json", DocumentType.QUESTIONNAIRE, key)
        )
    docs.append(ReferenceDocument("policies/company_privacy_policy.md", DocumentType.POLICY, None))
    for agreement in sorted((datasets / "policies" / "vendor_agreements").glob("*.md")):
        docs.append(
            ReferenceDocument(
                f"policies/vendor_agreements/{agreement.name}",
                DocumentType.VENDOR_AGREEMENT,
                None,
            )
        )
    return docs


def ingest_reference_documents(
    db: Session,
    embedder: Embedder,
    system_ids: dict[str, uuid.UUID],
    datasets: Path = DATASETS,
) -> int:
    """Index the policies, questionnaires and agreements of the estate. Returns the chunk count."""
    ingestor = DocumentIngestor(db, embedder)
    total = 0
    for doc in reference_documents(datasets):
        content = (datasets / doc.path).read_bytes()
        result = ingestor.ingest(
            filename=Path(doc.path).name,
            content=content,
            doc_type=doc.doc_type,
            system_id=system_ids.get(doc.system_key) if doc.system_key else None,
            source_uri=doc.path,
        )
        total += result.chunks
    return total


@dataclass(frozen=True)
class GoldQuestion:
    id: str
    question: str
    relevant: list[dict[str, Any]]
    system: str | None = None
    doc_type: DocumentType | None = None


def load_gold(path: Path = GOLD_FILE) -> list[GoldQuestion]:
    data = json.loads(path.read_text(encoding="utf-8"))
    questions = []
    for item in data["questions"]:
        filters = item.get("filters", {})
        questions.append(
            GoldQuestion(
                id=item["id"],
                question=item["question"],
                relevant=item["relevant"],
                system=filters.get("system"),
                doc_type=DocumentType(filters["doc_type"]) if "doc_type" in filters else None,
            )
        )
    return questions


def matches(passage: Passage, predicate: dict[str, Any]) -> bool:
    for key, wanted in predicate.items():
        have = passage.metadata.get(key)
        if key == "article" and passage.source != "regulation":
            return False
        if key in ("source_uri", "heading") and passage.source != "document":
            return False
        if have != wanted:
            return False
    return True


@dataclass
class RecallReport:
    total: int = 0
    hits: int = 0
    misses: list[str] = field(default_factory=list)
    first_rank: list[int | None] = field(default_factory=list)
    latencies_ms: list[float] = field(default_factory=list)

    @property
    def recall(self) -> float:
        return self.hits / self.total if self.total else 0.0

    @property
    def p50_ms(self) -> float:
        return statistics.median(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def p95_ms(self) -> float:
        ordered = sorted(self.latencies_ms)
        return ordered[int(0.95 * (len(ordered) - 1))] if ordered else 0.0

    @property
    def mrr(self) -> float:
        return sum(1 / r for r in self.first_rank if r) / self.total if self.total else 0.0


def evaluate_recall(
    retriever: HybridRetriever,
    questions: list[GoldQuestion],
    system_ids: dict[str, uuid.UUID],
    *,
    k: int = 5,
    rerank: bool | None = None,
) -> RecallReport:
    report = RecallReport()
    for q in questions:
        filters = Filters(
            system_id=system_ids[q.system] if q.system else None,
            doc_types=(q.doc_type,) if q.doc_type else (),
        )
        result = retriever.search(q.question, top_k=k, filters=filters, rerank=rerank)
        rank = next(
            (
                position
                for position, passage in enumerate(result.passages, start=1)
                if any(matches(passage, predicate) for predicate in q.relevant)
            ),
            None,
        )
        report.total += 1
        report.first_rank.append(rank)
        report.latencies_ms.append(result.timings_ms["total"])
        if rank is None:
            report.misses.append(q.id)
        else:
            report.hits += 1
    return report
