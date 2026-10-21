import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import func, select

from app.api.deps import (
    ALL_ROLES,
    Principal,
    app_settings,
    get_visible_system,
    require_role,
    write_audit,
)
from app.api.schemas import (
    DocumentOut,
    IngestItemOut,
    KnowledgeSearchIn,
    KnowledgeSearchOut,
    PassageOut,
)
from app.api.tenancy import get_tenant_db
from app.classify.embedder import Embedder
from app.core.config import Settings
from app.core.uploads import UploadRejectedError, validate_upload
from app.db.enums import DocumentType, EvidenceKind, Role
from app.db.models import Document, DocumentChunk, RegulationChunk, System
from app.db.session import TenantSession
from app.knowledge.chunking import UnreadableDocumentError
from app.knowledge.ingest import DocumentIngestor, IngestResult, ingest_system_evidence
from app.knowledge.retrieval import Filters, HybridRetriever, Passage, Reranker
from app.services.evidence_store import EvidenceStore

router = APIRouter(prefix="/api/v1", tags=["knowledge"])

EDITORS = (Role.ADMIN, Role.ANALYST)
UPLOADERS = (Role.ADMIN, Role.ANALYST, Role.SYSTEM_OWNER)
UPLOAD_KIND = {
    DocumentType.POLICY: EvidenceKind.PRIVACY_POLICY,
    DocumentType.GUIDANCE: EvidenceKind.PRIVACY_POLICY,
    DocumentType.VENDOR_AGREEMENT: EvidenceKind.VENDOR_AGREEMENT,
    DocumentType.QUESTIONNAIRE: EvidenceKind.QUESTIONNAIRE,
}


def get_embedder(request: Request) -> Embedder:
    embedder: Embedder = request.app.state.embedder
    return embedder


def get_reranker(request: Request) -> Reranker | None:
    reranker: Reranker | None = request.app.state.reranker
    return reranker


def _scope(principal: Principal) -> Filters:
    """A system owner sees organisation wide documents and those of their own systems."""
    return Filters(owner_user_id=principal.user_id if principal.role is Role.SYSTEM_OWNER else None)


def _passage_out(passage: Passage) -> PassageOut:
    return PassageOut(
        id=passage.id,
        source=passage.source,
        citation=passage.citation,
        label=passage.label,
        text=passage.text,
        score=passage.score,
        signals=passage.signals,
        metadata=passage.metadata,
    )


@router.post("/knowledge/search", response_model=KnowledgeSearchOut)
def search_knowledge(
    body: KnowledgeSearchIn,
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
    embedder: Embedder = Depends(get_embedder),
    reranker: Reranker | None = Depends(get_reranker),
    settings: Settings = Depends(app_settings),
) -> KnowledgeSearchOut:
    """Hybrid (full text + vector) search; every passage has an id and a stable citation."""
    if not (
        db.scalar(select(func.count()).select_from(RegulationChunk).limit(1))
        or db.scalar(select(func.count()).select_from(DocumentChunk).limit(1))
    ):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The knowledge base is empty (run scripts/ingest_regulation.py)",
        )
    if body.system_id is not None:
        get_visible_system(db, principal, body.system_id)
    scope = _scope(principal)
    filters = Filters(
        system_id=body.system_id,
        doc_types=tuple(body.doc_types),
        articles=tuple(body.articles),
        sources=tuple(body.sources),
        owner_user_id=scope.owner_user_id,
    )
    retriever = HybridRetriever(db, embedder, reranker, candidates=settings.retrieval_candidates)
    result = retriever.search(
        body.query,
        top_k=body.top_k,
        filters=filters,
        rerank=body.rerank if body.rerank is not None else reranker is not None,
    )
    return KnowledgeSearchOut(
        passages=[_passage_out(p) for p in result.passages],
        reranked=result.reranked,
        timings_ms=result.timings_ms,
    )


@router.get("/knowledge/passage", response_model=PassageOut)
def get_passage(
    citation: Annotated[str, Query(min_length=5, max_length=120)],
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
    embedder: Embedder = Depends(get_embedder),
) -> PassageOut:
    """The passage a citation points at, so a claim can be checked against its source."""
    passage = HybridRetriever(db, embedder).resolve_citation(citation, _scope(principal))
    if passage is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Passage not found")
    return _passage_out(passage)


@router.get("/knowledge/documents", response_model=list[DocumentOut])
def list_documents(
    system_id: uuid.UUID | None = None,
    doc_type: DocumentType | None = None,
    principal: Principal = Depends(require_role(*ALL_ROLES)),
    db: TenantSession = Depends(get_tenant_db),
) -> list[DocumentOut]:
    counts = (
        select(DocumentChunk.document_id, func.count().label("n"))
        .group_by(DocumentChunk.document_id)
        .subquery()
    )
    stmt = (
        select(Document, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.document_id == Document.id)
        .order_by(Document.created_at.desc())
        .limit(500)
    )
    if system_id is not None:
        get_visible_system(db, principal, system_id)
        stmt = stmt.where(Document.system_id == system_id)
    if doc_type is not None:
        stmt = stmt.where(Document.doc_type == doc_type)
    if principal.role is Role.SYSTEM_OWNER:
        owned = select(System.id).where(System.owner_user_id == principal.user_id)
        stmt = stmt.where(Document.system_id.is_(None) | Document.system_id.in_(owned))
    return [
        DocumentOut.model_validate(doc).model_copy(update={"chunks": int(n)})
        for doc, n in db.execute(stmt)
    ]


@router.post("/knowledge/documents", response_model=IngestItemOut, status_code=201)
def upload_document(
    request: Request,
    doc_type: Annotated[DocumentType, Form()],
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=300)] = None,
    system_id: Annotated[uuid.UUID | None, Form()] = None,
    principal: Principal = Depends(require_role(*EDITORS)),
    db: TenantSession = Depends(get_tenant_db),
    settings: Settings = Depends(app_settings),
    embedder: Embedder = Depends(get_embedder),
) -> IngestItemOut:
    """Index a policy, agreement or questionnaire (organisation wide, or for one system)."""
    if system_id is not None:
        get_visible_system(db, principal, system_id)
    content = file.file.read(settings.max_upload_bytes + 1)
    try:
        filename = validate_upload(
            file.filename or "upload", UPLOAD_KIND[doc_type], content, settings.max_upload_bytes
        )
        result = DocumentIngestor(db, embedder, settings.chunk_max_chars).ingest(
            filename=filename,
            content=content,
            doc_type=doc_type,
            title=title,
            system_id=system_id,
        )
    except (UploadRejectedError, UnreadableDocumentError) as exc:
        code = exc.status_code if isinstance(exc, UploadRejectedError) else 422
        raise HTTPException(code, str(exc)) from exc
    write_audit(
        db,
        request,
        "knowledge.document_ingested",
        principal=principal,
        entity_type="document",
        entity_id=result.document_id,
        details={"doc_type": doc_type.value, "chunks": result.chunks, "status": result.status},
    )
    db.commit()
    return _ingest_out(result)


@router.delete("/knowledge/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    request: Request,
    document_id: uuid.UUID,
    principal: Principal = Depends(require_role(*EDITORS)),
    db: TenantSession = Depends(get_tenant_db),
) -> None:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    write_audit(
        db,
        request,
        "knowledge.document_deleted",
        principal=principal,
        entity_type="document",
        entity_id=document.id,
        details={"title": document.title},
    )
    db.delete(document)
    db.commit()


@router.post("/systems/{system_id}/knowledge/ingest", response_model=list[IngestItemOut])
def ingest_system_documents(
    request: Request,
    system_id: uuid.UUID,
    principal: Principal = Depends(require_role(*UPLOADERS)),
    db: TenantSession = Depends(get_tenant_db),
    settings: Settings = Depends(app_settings),
    embedder: Embedder = Depends(get_embedder),
) -> list[IngestItemOut]:
    """Index the policy, questionnaire and agreements uploaded as evidence for the system."""
    system = get_visible_system(db, principal, system_id)
    store: EvidenceStore = request.app.state.evidence_store
    results = ingest_system_evidence(db, embedder, store, system, settings.chunk_max_chars)
    write_audit(
        db,
        request,
        "knowledge.system_ingested",
        principal=principal,
        entity_type="system",
        entity_id=system.id,
        details={"documents": len(results)},
    )
    db.commit()
    return [
        (
            _ingest_out(r)
            if isinstance(r, IngestResult)
            else IngestItemOut(title=r[0], status="skipped", detail=r[1])
        )
        for r in results
    ]


def _ingest_out(result: IngestResult) -> IngestItemOut:
    return IngestItemOut(
        document_id=result.document_id,
        title=result.title,
        chunks=result.chunks,
        status=result.status,
    )
