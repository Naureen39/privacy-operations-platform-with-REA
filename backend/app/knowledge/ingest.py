"""Load the regulation text (shared, owner role) and documents (per organisation) into the
knowledge tables with embeddings. Full text vectors are generated columns, so only the embedding
is computed here. Ingestion is idempotent: unchanged content is not embedded again."""

import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from app.classify.embedder import Embedder
from app.db.enums import DocumentType, EvidenceKind
from app.db.models import Document, DocumentChunk, EvidenceItem, RegulationChunk, System
from app.knowledge.chunking import (
    DEFAULT_MAX_CHARS,
    Chunk,
    UnreadableDocumentError,
    chunk_document,
)
from app.knowledge.retrieval import regulation_label
from app.services.evidence_store import EvidenceStore

REGULATION_FILE = (
    Path(__file__).resolve().parents[3] / "datasets" / "regulation" / "gdpr_articles.json"
)
EVIDENCE_DOC_TYPES: dict[EvidenceKind, DocumentType] = {
    EvidenceKind.PRIVACY_POLICY: DocumentType.POLICY,
    EvidenceKind.VENDOR_AGREEMENT: DocumentType.VENDOR_AGREEMENT,
    EvidenceKind.QUESTIONNAIRE: DocumentType.QUESTIONNAIRE,
}
MAX_CHUNKS_PER_DOCUMENT = 2000
BATCH = 64

Status = Literal["created", "replaced", "unchanged"]


def regulation_embedding_text(row: dict[str, Any]) -> str:
    label = regulation_label(int(row["article"]), row.get("paragraph"), row.get("title"))
    return f"{label}: {row['text']}"


def load_regulation(
    engine: Engine, embedder: Embedder, path: Path = REGULATION_FILE, force: bool = False
) -> int:
    """Insert or update the regulation chunks with the owner role (the application role can only
    read the table). Returns the number of chunks; nothing is embedded when the text, the model
    and the chunk keys are unchanged."""
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data["chunks"]
    with engine.begin() as conn:
        session = Session(bind=conn)
        existing = {r.chunk_key: r for r in session.scalars(select(RegulationChunk))}
        unchanged = (
            not force
            and len(existing) == len(rows)
            and all(
                (c := existing.get(r["id"])) is not None
                and c.text == r["text"]
                and c.embedding is not None
                for r in rows
            )
            and _same_model(existing, rows, embedder)
        )
        if unchanged:
            return len(rows)
        for key in set(existing) - {r["id"] for r in rows}:
            session.delete(existing[key])
        pending: list[tuple[RegulationChunk, str]] = []
        for r in rows:
            chunk = existing.get(r["id"])
            if chunk is None:
                chunk = RegulationChunk(chunk_key=r["id"])
                session.add(chunk)
            chunk.regulation = r.get("regulation", "GDPR")
            chunk.chapter = r.get("chapter")
            chunk.article = int(r["article"])
            chunk.paragraph = r.get("paragraph")
            chunk.title = r.get("title")
            chunk.text = r["text"]
            pending.append((chunk, regulation_embedding_text(r)))
        for start in range(0, len(pending), BATCH):
            part = pending[start : start + BATCH]
            for (chunk, _), vector in zip(part, embedder.embed([t for _, t in part]), strict=True):
                chunk.embedding = vector
        session.flush()
        return len(rows)


def _same_model(
    existing: dict[str, RegulationChunk], rows: list[dict[str, Any]], embedder: Embedder
) -> bool:
    """Embed one stored chunk again: a different model (or text recipe) gives a different vector."""
    row = rows[0]
    stored = existing[row["id"]].embedding
    if stored is None:
        return False
    fresh = embedder.embed([regulation_embedding_text(row)])[0]
    dot = sum(float(x) * float(y) for x, y in zip(stored, fresh, strict=True))
    norm = math.sqrt(sum(float(x) ** 2 for x in stored) * sum(y**2 for y in fresh))
    return norm > 0 and dot / norm > 0.999


@dataclass(frozen=True)
class IngestResult:
    document_id: uuid.UUID
    title: str
    chunks: int
    status: Status


def checksum_of(content: bytes, max_chars: int, embedder_name: str) -> str:
    """Changes when the content, the chunk size or the embedding model changes."""
    digest = hashlib.sha256(content)
    digest.update(f"|{max_chars}|{embedder_name}".encode())
    return digest.hexdigest()


class DocumentIngestor:
    def __init__(self, db: Session, embedder: Embedder, max_chars: int = DEFAULT_MAX_CHARS) -> None:
        self.db = db
        self.embedder = embedder
        self.max_chars = max_chars

    def ingest(
        self,
        *,
        filename: str,
        content: bytes,
        doc_type: DocumentType,
        title: str | None = None,
        system_id: uuid.UUID | None = None,
        evidence_item_id: uuid.UUID | None = None,
        source_uri: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> IngestResult:
        """Chunk, embed and store one document, replacing an earlier version of it. A document is
        identified by its evidence item or, for uploads, by (system, source, type)."""
        document_title, chunks = chunk_document(filename, content, self.max_chars)
        if not chunks:
            raise UnreadableDocumentError("The document contains no text")
        if len(chunks) > MAX_CHUNKS_PER_DOCUMENT:
            raise UnreadableDocumentError("The document is too large to index")
        source = source_uri or filename
        checksum = checksum_of(content, self.max_chars, self.embedder.name)
        existing = self._find(evidence_item_id, system_id, source, doc_type)
        status: Status = "created"
        if existing is not None:
            has_all = self._complete(existing.id, len(chunks))
            if existing.checksum_sha256 == checksum and has_all:
                return IngestResult(existing.id, existing.title, len(chunks), "unchanged")
            self.db.execute(delete(Document).where(Document.id == existing.id))
            self.db.flush()
            status = "replaced"
        document = Document(
            id=uuid.uuid4(),
            system_id=system_id,
            evidence_item_id=evidence_item_id,
            doc_type=doc_type,
            title=(title or document_title or filename)[:300],
            source_uri=source[:2000],
            checksum_sha256=checksum,
            doc_metadata={"filename": filename, "chunks": len(chunks), **(metadata or {})},
        )
        self.db.add(document)
        self.db.flush()
        self._store_chunks(document, chunks, system_id)
        return IngestResult(document.id, document.title, len(chunks), status)

    def _store_chunks(
        self, document: Document, chunks: list[Chunk], system_id: uuid.UUID | None
    ) -> None:
        for start in range(0, len(chunks), BATCH):
            part = chunks[start : start + BATCH]
            vectors = self.embedder.embed([f"{document.title}. {c.embedding_text}" for c in part])
            self.db.add_all(
                DocumentChunk(
                    document_id=document.id,
                    system_id=system_id,
                    chunk_index=c.index,
                    heading=(c.heading or None) and c.heading[:300],
                    page=c.page,
                    text=c.text,
                    token_count=c.token_count,
                    embedding=v,
                )
                for c, v in zip(part, vectors, strict=True)
            )
        self.db.flush()

    def _find(
        self,
        evidence_item_id: uuid.UUID | None,
        system_id: uuid.UUID | None,
        source: str,
        doc_type: DocumentType,
    ) -> Document | None:
        stmt = select(Document).where(Document.doc_type == doc_type)
        if evidence_item_id is not None:
            stmt = stmt.where(Document.evidence_item_id == evidence_item_id)
        else:
            stmt = stmt.where(
                Document.evidence_item_id.is_(None),
                Document.source_uri == source[:2000],
                (
                    Document.system_id.is_(None)
                    if system_id is None
                    else Document.system_id == system_id
                ),
            )
        return self.db.scalars(stmt.order_by(Document.created_at)).first()

    def _complete(self, document_id: uuid.UUID, expected: int) -> bool:
        count, embedded = self.db.execute(
            select(func.count(), func.count(DocumentChunk.embedding)).where(
                DocumentChunk.document_id == document_id
            )
        ).one()
        return bool(count == expected and embedded == expected)


def ingest_system_evidence(
    db: Session,
    embedder: Embedder,
    store: EvidenceStore,
    system: System,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[IngestResult | tuple[str, str]]:
    """Index the policy, questionnaire and agreements uploaded for a system. A file that cannot be
    read is reported as (filename, reason) and does not stop the others."""
    ingestor = DocumentIngestor(db, embedder, max_chars)
    items = db.scalars(
        select(EvidenceItem)
        .where(
            EvidenceItem.system_id == system.id,
            EvidenceItem.kind.in_(list(EVIDENCE_DOC_TYPES)),
        )
        .order_by(EvidenceItem.created_at)
    ).all()
    results: list[IngestResult | tuple[str, str]] = []
    for item in items:
        try:
            content = store.read(item.storage_path, item.id)
            results.append(
                ingestor.ingest(
                    filename=item.filename,
                    content=content,
                    doc_type=EVIDENCE_DOC_TYPES[item.kind],
                    title=f"{_kind_title(item.kind)}: {system.name}",
                    system_id=system.id,
                    evidence_item_id=item.id,
                    source_uri=item.filename,
                    metadata={"evidence_kind": item.kind.value},
                )
            )
        except (UnreadableDocumentError, OSError) as exc:
            results.append((item.filename, str(exc)))
    return results


def _kind_title(kind: EvidenceKind) -> str:
    return {
        EvidenceKind.PRIVACY_POLICY: "Privacy notice",
        EvidenceKind.VENDOR_AGREEMENT: "Vendor agreement",
        EvidenceKind.QUESTIONNAIRE: "Questionnaire",
    }[kind]
