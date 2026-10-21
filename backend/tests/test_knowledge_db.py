"""Ingestion and retrieval against PostgreSQL with the hashing embedder (no model needed):
idempotency, replacement, tenant isolation, owner scoping, filters and citations."""

import json
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.classify.embedder import HashingEmbedder
from app.db.enums import DocumentType, Role
from app.db.models import Document, DocumentChunk, RegulationChunk, System
from app.db.session import (
    TenantContext,
    TenantSession,
    make_engine,
    make_session_factory,
    set_tenant,
)
from app.knowledge.ingest import DocumentIngestor, load_regulation
from app.knowledge.retrieval import Filters, HybridRetriever
from app.services import provisioning
from tests.conftest import alembic_config, app_url, create_database

EMBEDDER = HashingEmbedder()

REGULATION = {
    "chunks": [
        {"id": "gdpr-art5-p1", "regulation": "GDPR", "chapter": "CHAPTER II", "article": 5,
         "paragraph": "1", "title": "Principles relating to processing",
         "text": "Personal data shall be processed lawfully and kept no longer than necessary."},
        {"id": "gdpr-art30-p1", "regulation": "GDPR", "chapter": "CHAPTER IV", "article": 30,
         "paragraph": "1", "title": "Records of processing activities",
         "text": "Each controller shall maintain a record of processing activities."},
        {"id": "gdpr-art33-p1", "regulation": "GDPR", "chapter": "CHAPTER IV", "article": 33,
         "paragraph": "1", "title": "Notification of a personal data breach",
         "text": "The controller shall notify the supervisory authority within 72 hours."},
    ]
}  # fmt: skip

POLICY = b"# Notice\n\n## Retention\n\nTickets are kept for twelve months.\n\n## Sharing\n\nWe share data with Stripe.\n"


@pytest.fixture(scope="module")
def kb_url(admin_url: URL) -> URL:
    url = create_database(admin_url, f"kb_{uuid.uuid4().hex[:8]}")
    command.upgrade(alembic_config(url.render_as_string(hide_password=False)), "head")
    return url


@pytest.fixture(scope="module")
def kb_owner(kb_url: URL) -> Iterator[Engine]:
    engine = create_engine(kb_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def kb_factory(kb_url: URL) -> Iterator[sessionmaker[TenantSession]]:
    engine = make_engine(app_url(kb_url).render_as_string(hide_password=False), pool_size=2)
    yield make_session_factory(engine)
    engine.dispose()


@pytest.fixture(scope="module")
def regulation_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("reg") / "gdpr.json"
    path.write_text(json.dumps(REGULATION), encoding="utf-8")
    return path


@pytest.fixture
def tenant(
    kb_owner: Engine, kb_factory: sessionmaker[TenantSession]
) -> Iterator[tuple[uuid.UUID, TenantSession]]:
    org_id = provisioning.create_organization(kb_owner, "KB", f"kb-{uuid.uuid4().hex[:8]}")
    with kb_factory() as db:
        set_tenant(db, TenantContext(org_id=org_id))
        yield org_id, db


def count(db: TenantSession, model: type) -> int:
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


def test_regulation_load_is_idempotent_and_updates_changed_text(
    kb_owner: Engine, regulation_file: Path
) -> None:
    assert load_regulation(kb_owner, EMBEDDER, regulation_file) == 3
    with kb_owner.connect() as conn:
        first = conn.execute(text("SELECT chunk_key, id FROM regulation_chunks")).all()
    assert load_regulation(kb_owner, EMBEDDER, regulation_file) == 3
    with kb_owner.connect() as conn:
        assert sorted(
            conn.execute(text("SELECT chunk_key, id FROM regulation_chunks")).all()
        ) == sorted(first)

    changed = json.loads(regulation_file.read_text(encoding="utf-8"))
    changed["chunks"][1]["text"] = "Each controller keeps a register of all processing."
    changed["chunks"].pop()
    other = regulation_file.with_name("gdpr2.json")
    other.write_text(json.dumps(changed), encoding="utf-8")
    assert load_regulation(kb_owner, EMBEDDER, other) == 2
    with kb_owner.connect() as conn:
        rows = dict(conn.execute(text("SELECT chunk_key, text FROM regulation_chunks")).all())
        assert set(rows) == {"gdpr-art5-p1", "gdpr-art30-p1"}
        assert rows["gdpr-art30-p1"].startswith("Each controller keeps")
        assert (
            conn.execute(
                text("SELECT count(*) FROM regulation_chunks WHERE embedding IS NULL")
            ).scalar_one()
            == 0
        )
    load_regulation(kb_owner, EMBEDDER, regulation_file)  # restore for the other tests


def test_application_role_cannot_write_regulation_chunks(
    kb_factory: sessionmaker[TenantSession], regulation_file: Path, kb_owner: Engine
) -> None:
    load_regulation(kb_owner, EMBEDDER, regulation_file)
    with kb_factory() as db:
        db.add(RegulationChunk(chunk_key="evil", article=1, text="x"))
        with pytest.raises(Exception, match="permission denied"):
            db.flush()


def test_ingest_creates_chunks_with_embeddings_and_is_idempotent(
    tenant: tuple[uuid.UUID, TenantSession],
) -> None:
    _, db = tenant
    ingestor = DocumentIngestor(db, EMBEDDER)
    first = ingestor.ingest(
        filename="policy.md", content=POLICY, doc_type=DocumentType.POLICY, title="Notice A"
    )
    db.commit()
    assert first.status == "created" and first.chunks == 2
    again = ingestor.ingest(
        filename="policy.md", content=POLICY, doc_type=DocumentType.POLICY, title="Notice A"
    )
    assert again.status == "unchanged" and again.document_id == first.document_id
    assert count(db, Document) == 1 and count(db, DocumentChunk) == 2
    chunks = db.scalars(select(DocumentChunk).order_by(DocumentChunk.chunk_index)).all()
    assert [c.heading for c in chunks] == ["Retention", "Sharing"]
    assert all(c.embedding is not None and c.token_count > 0 for c in chunks)
    tsv_ok = db.scalar(
        select(func.count()).where(
            DocumentChunk.tsv.op("@@")(func.to_tsquery("english", "retention"))
        )
    )
    assert tsv_ok == 1  # the heading is searchable even though the paragraph never says it


def test_changed_content_replaces_the_document(tenant: tuple[uuid.UUID, TenantSession]) -> None:
    _, db = tenant
    ingestor = DocumentIngestor(db, EMBEDDER)
    old = ingestor.ingest(filename="policy.md", content=POLICY, doc_type=DocumentType.POLICY)
    new = ingestor.ingest(
        filename="policy.md",
        content=POLICY.replace(b"twelve", b"six"),
        doc_type=DocumentType.POLICY,
    )
    db.commit()
    assert new.status == "replaced" and new.document_id != old.document_id
    assert count(db, Document) == 1
    texts = " ".join(db.scalars(select(DocumentChunk.text)).all())
    assert "six months" in texts and "twelve" not in texts


def test_a_different_chunk_size_or_model_reindexes(tenant: tuple[uuid.UUID, TenantSession]) -> None:
    _, db = tenant
    DocumentIngestor(db, EMBEDDER, 900).ingest(
        filename="p.md", content=POLICY, doc_type=DocumentType.POLICY
    )
    smaller = DocumentIngestor(db, EMBEDDER, 400).ingest(
        filename="p.md", content=POLICY, doc_type=DocumentType.POLICY
    )
    assert smaller.status == "replaced"


def test_unreadable_documents_leave_nothing_behind(tenant: tuple[uuid.UUID, TenantSession]) -> None:
    from app.knowledge.chunking import UnreadableDocumentError

    _, db = tenant
    with pytest.raises(UnreadableDocumentError):
        DocumentIngestor(db, EMBEDDER).ingest(
            filename="empty.md", content=b"\n\n", doc_type=DocumentType.POLICY
        )
    assert count(db, Document) == 0


def test_organisations_cannot_search_each_others_documents(
    kb_owner: Engine, kb_factory: sessionmaker[TenantSession], regulation_file: Path
) -> None:
    load_regulation(kb_owner, EMBEDDER, regulation_file)
    org_a = provisioning.create_organization(kb_owner, "A", f"a-{uuid.uuid4().hex[:8]}")
    org_b = provisioning.create_organization(kb_owner, "B", f"b-{uuid.uuid4().hex[:8]}")
    with kb_factory() as db:
        set_tenant(db, TenantContext(org_id=org_a))
        DocumentIngestor(db, EMBEDDER).ingest(
            filename="secret.md",
            content=b"## Plans\n\nProject Zephyr acquisition is confidential.",
            doc_type=DocumentType.POLICY,
        )
        db.commit()
    for org, expected in ((org_a, 1), (org_b, 0)):
        with kb_factory() as db:
            set_tenant(db, TenantContext(org_id=org))
            result = HybridRetriever(db, EMBEDDER).search(
                "Zephyr acquisition confidential", top_k=10
            )
            docs = [p for p in result.passages if p.source == "document"]
            assert len(docs) == expected
            assert any(
                p.source == "regulation" for p in result.passages
            )  # shared text stays visible
    with kb_factory() as db:
        set_tenant(db, TenantContext(org_id=org_b))
        with kb_owner.connect() as conn:
            a_doc_id = conn.execute(text("SELECT id FROM documents LIMIT 1")).scalar_one()
        assert HybridRetriever(db, EMBEDDER).resolve_citation(f"doc:{a_doc_id}#0") is None


def test_filters_by_system_type_and_article(
    tenant: tuple[uuid.UUID, TenantSession], kb_owner: Engine, regulation_file: Path
) -> None:
    load_regulation(kb_owner, EMBEDDER, regulation_file)
    org_id, db = tenant
    shop = System(org_id=org_id, name="Shop", slug="shop")
    crm = System(org_id=org_id, name="CRM", slug="crm")
    db.add_all([shop, crm])
    db.flush()
    ingestor = DocumentIngestor(db, EMBEDDER)
    ingestor.ingest(
        filename="shop.md",
        content=POLICY,
        doc_type=DocumentType.POLICY,
        system_id=shop.id,
        source_uri="shop.md",
    )
    ingestor.ingest(
        filename="crm.md",
        content=POLICY,
        doc_type=DocumentType.POLICY,
        system_id=crm.id,
        source_uri="crm.md",
    )
    ingestor.ingest(
        filename="dpa.md", content=b"## Subject\n\nThe processor stores tickets for twelve months.",
        doc_type=DocumentType.VENDOR_AGREEMENT, source_uri="dpa.md",
    )  # fmt: skip
    db.commit()
    retriever = HybridRetriever(db, EMBEDDER)
    query = "tickets kept for twelve months"

    by_system = retriever.search(query, top_k=10, filters=Filters(system_id=shop.id)).passages
    assert by_system and {p.metadata["system_id"] for p in by_system} == {str(shop.id)}

    by_type = retriever.search(
        query, top_k=10, filters=Filters(doc_types=(DocumentType.VENDOR_AGREEMENT,))
    ).passages
    assert by_type and {p.metadata["doc_type"] for p in by_type} == {"vendor_agreement"}

    articles = retriever.search(
        "controller shall notify", top_k=10, filters=Filters(articles=(33,))
    ).passages
    assert [p.metadata["article"] for p in articles] == [33]
    assert articles[0].source == "regulation"

    only_regulation = retriever.search(
        query, top_k=10, filters=Filters(sources=("regulation",))
    ).passages
    assert only_regulation and all(p.source == "regulation" for p in only_regulation)


def test_system_owner_scope_hides_other_systems(
    tenant: tuple[uuid.UUID, TenantSession], kb_owner: Engine
) -> None:
    org_id, db = tenant
    owner = provisioning.create_user(
        kb_owner,
        org_id,
        f"o-{uuid.uuid4().hex[:6]}@x.example",
        "Owner",
        "Passw0rd!long",
        Role.SYSTEM_OWNER,
    )
    mine = System(org_id=org_id, name="Mine", slug="mine", owner_user_id=owner.id)
    theirs = System(org_id=org_id, name="Theirs", slug="theirs")
    db.add_all([mine, theirs])
    db.flush()
    ingestor = DocumentIngestor(db, EMBEDDER)
    for system, name in ((mine, "mine.md"), (theirs, "theirs.md"), (None, "company.md")):
        ingestor.ingest(
            filename=name, content=b"## Scope\n\nBackups are retained for thirty days.",
            doc_type=DocumentType.POLICY, system_id=system.id if system else None, source_uri=name,
        )  # fmt: skip
    db.commit()
    retriever = HybridRetriever(db, EMBEDDER)
    scoped = retriever.search(
        "backups retained thirty days",
        top_k=10,
        filters=Filters(owner_user_id=owner.id, sources=("document",)),
    )
    assert sorted(p.metadata["source_uri"] for p in scoped.passages) == ["company.md", "mine.md"]
    everything = retriever.search(
        "backups retained thirty days", top_k=10, filters=Filters(sources=("document",))
    )
    assert len(everything.passages) == 3


def test_citations_resolve_to_the_same_passage(
    tenant: tuple[uuid.UUID, TenantSession], kb_owner: Engine, regulation_file: Path
) -> None:
    load_regulation(kb_owner, EMBEDDER, regulation_file)
    _, db = tenant
    DocumentIngestor(db, EMBEDDER).ingest(
        filename="p.md", content=POLICY, doc_type=DocumentType.POLICY
    )
    db.commit()
    retriever = HybridRetriever(db, EMBEDDER)
    found = retriever.search("records of processing activities retention", top_k=10).passages
    assert {p.source for p in found} == {"regulation", "document"}
    for passage in found:
        assert passage.id and passage.citation.split(":")[0] in ("reg", "doc") and passage.label
        again = retriever.resolve_citation(passage.citation)
        assert again is not None and again.id == passage.id and again.text == passage.text
    assert retriever.resolve_citation("reg:gdpr-art999-p9") is None
    assert retriever.resolve_citation("doc:not-a-uuid#1") is None
    assert retriever.resolve_citation("junk") is None


def test_search_signals_show_which_lists_found_the_passage(
    tenant: tuple[uuid.UUID, TenantSession], kb_owner: Engine, regulation_file: Path
) -> None:
    load_regulation(kb_owner, EMBEDDER, regulation_file)
    _, db = tenant
    top = (
        HybridRetriever(db, EMBEDDER)
        .search("controller shall maintain a record of processing activities", top_k=1)
        .passages[0]
    )
    assert top.metadata["article"] == 30
    assert top.signals["vector_rank"] == 1 and top.signals["fulltext_rank"] == 1
    assert top.score == pytest.approx(2 / 61, abs=1e-5)


def test_fulltext_only_and_vector_only_modes_work(
    tenant: tuple[uuid.UUID, TenantSession], kb_owner: Engine, regulation_file: Path
) -> None:
    load_regulation(kb_owner, EMBEDDER, regulation_file)
    _, db = tenant
    text_only = (
        HybridRetriever(db, EMBEDDER, mode="fulltext")
        .search("supervisory authority 72 hours", top_k=3)
        .passages
    )
    assert text_only[0].metadata["article"] == 33 and "vector_rank" not in text_only[0].signals
    vector_only = (
        HybridRetriever(db, EMBEDDER, mode="vector")
        .search("supervisory authority 72 hours", top_k=3)
        .passages
    )
    assert (
        vector_only[0].metadata["article"] == 33 and "fulltext_rank" not in vector_only[0].signals
    )
    assert (
        HybridRetriever(db, EMBEDDER).search("the of and", top_k=3).passages
    )  # only stop words: vector still answers


class ShiftedEmbedder(HashingEmbedder):
    """Another model: same dimensions, different vectors."""

    name = "shifted-384"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [v[1:] + v[:1] for v in super().embed([t + " shifted" for t in texts])]


def test_a_different_embedding_model_reloads_the_regulation(
    kb_owner: Engine, regulation_file: Path
) -> None:
    load_regulation(kb_owner, EMBEDDER, regulation_file, force=True)
    with kb_owner.connect() as conn:
        before = conn.execute(
            text("SELECT embedding::text FROM regulation_chunks ORDER BY chunk_key LIMIT 1")
        ).scalar_one()
    load_regulation(kb_owner, EMBEDDER, regulation_file)  # same model: nothing to do
    load_regulation(kb_owner, ShiftedEmbedder(), regulation_file)
    with kb_owner.connect() as conn:
        after = conn.execute(
            text("SELECT embedding::text FROM regulation_chunks ORDER BY chunk_key LIMIT 1")
        ).scalar_one()
    assert before != after
    load_regulation(kb_owner, EMBEDDER, regulation_file)
