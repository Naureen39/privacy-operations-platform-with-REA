"""Phase 6 acceptance: recall at 5 of at least 90 percent on the 40 question gold set, with the
real embedding model, over the GDPR text and the policies, questionnaires and agreements of the
reference estate. The questions were written before any tuning (datasets/evaluation)."""

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.classify.embedder import SentenceTransformerEmbedder
from app.db.session import TenantContext, TenantSession, set_tenant
from app.knowledge.evaluation import evaluate_recall, load_gold
from app.knowledge.retrieval import CrossEncoderReranker, HybridRetriever
from tests.fixtures_knowledge import KnowledgeOrg

GOLD = load_gold()


@pytest.fixture
def db(
    session_factory: sessionmaker[TenantSession], knowledge_org: KnowledgeOrg
) -> Iterator[Session]:
    with session_factory() as session:
        set_tenant(session, TenantContext(org_id=knowledge_org.org_id))
        yield session


def test_the_reference_estate_is_fully_indexed(knowledge_org: KnowledgeOrg, db: Session) -> None:
    from sqlalchemy import func, select

    from app.db.models import Document, DocumentChunk, RegulationChunk

    assert db.scalar(select(func.count()).select_from(RegulationChunk)) == 412
    assert db.scalar(select(func.count()).select_from(Document)) == 8 * 2 + 1 + 9
    assert db.scalar(select(func.count()).select_from(DocumentChunk)) == knowledge_org.chunks
    unembedded = db.scalar(
        select(func.count()).select_from(DocumentChunk).where(DocumentChunk.embedding.is_(None))
    )
    assert unembedded == 0


def test_recall_at_five_is_at_least_ninety_percent(
    db: Session, real_embedder: SentenceTransformerEmbedder, knowledge_org: KnowledgeOrg
) -> None:
    report = evaluate_recall(HybridRetriever(db, real_embedder), GOLD, knowledge_org.system_ids)
    print(
        f"\n[gold] hybrid recall@5 {report.recall:.1%} ({report.hits}/{report.total}), "
        f"MRR {report.mrr:.3f}, p50 {report.p50_ms:.0f} ms, p95 {report.p95_ms:.0f} ms, "
        f"missed {report.misses}"
    )
    assert report.total == 40
    assert report.recall >= 0.90, report.misses


def test_regulation_and_document_questions_each_reach_ninety_percent(
    db: Session, real_embedder: SentenceTransformerEmbedder, knowledge_org: KnowledgeOrg
) -> None:
    retriever = HybridRetriever(db, real_embedder)
    for prefix in ("R", "D"):
        part = [q for q in GOLD if q.id.startswith(prefix)]
        report = evaluate_recall(retriever, part, knowledge_org.system_ids)
        assert report.recall >= 0.90, (prefix, report.misses)


def test_hybrid_is_not_worse_than_either_signal_alone(
    db: Session, real_embedder: SentenceTransformerEmbedder, knowledge_org: KnowledgeOrg
) -> None:
    results = {
        mode: evaluate_recall(
            HybridRetriever(db, real_embedder, mode=mode),  # type: ignore[arg-type]
            GOLD,
            knowledge_org.system_ids,
        )
        for mode in ("hybrid", "vector", "fulltext")
    }
    print(
        "\n[ablation] "
        + ", ".join(
            f"{m}: recall {r.recall:.1%} MRR {r.mrr:.3f} p50 {r.p50_ms:.0f} ms"
            for m, r in results.items()
        )
    )
    assert results["hybrid"].recall >= max(results["vector"].recall, results["fulltext"].recall)
    assert results["hybrid"].mrr >= results["fulltext"].mrr
    assert results["fulltext"].recall >= 0.6, "keyword search alone should find most answers"
    assert results["vector"].recall >= 0.85


def test_the_cross_encoder_improves_order_within_a_latency_budget(
    db: Session,
    real_embedder: SentenceTransformerEmbedder,
    real_reranker: CrossEncoderReranker,
    knowledge_org: KnowledgeOrg,
) -> None:
    retriever = HybridRetriever(db, real_embedder, real_reranker)
    plain = evaluate_recall(retriever, GOLD, knowledge_org.system_ids, rerank=False)
    reranked = evaluate_recall(retriever, GOLD, knowledge_org.system_ids, rerank=True)
    print(
        f"\n[rerank] recall {plain.recall:.1%} -> {reranked.recall:.1%}, "
        f"MRR {plain.mrr:.3f} -> {reranked.mrr:.3f}, "
        f"p50 {plain.p50_ms:.0f} -> {reranked.p50_ms:.0f} ms, p95 {reranked.p95_ms:.0f} ms"
    )
    assert reranked.recall >= 0.90
    assert reranked.mrr >= plain.mrr
    assert reranked.p95_ms < 2000


def test_every_returned_passage_carries_an_id_and_a_resolvable_citation(
    db: Session, real_embedder: SentenceTransformerEmbedder, knowledge_org: KnowledgeOrg
) -> None:
    retriever = HybridRetriever(db, real_embedder)
    for question in GOLD[::4]:
        for passage in retriever.search(question.question, top_k=5).passages:
            assert passage.id and passage.label and passage.text
            resolved = retriever.resolve_citation(passage.citation)
            assert resolved is not None and resolved.id == passage.id
