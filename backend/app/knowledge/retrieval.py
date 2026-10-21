"""Hybrid retrieval: full text and vector search over the regulation text and the organisation's
documents, merged by reciprocal rank fusion, with an optional cross encoder over the top results.

Every passage has an id and a stable citation (`reg:gdpr-art30-p1`, `doc:<document id>#<chunk>`),
so a downstream claim can point at the exact text that supports it and `resolve_citation` can
check that the text exists.
"""

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from sqlalchemy import Select, func, or_, select, text
from sqlalchemy.orm import Session

from app.classify.embedder import Embedder
from app.db.enums import DocumentType
from app.db.models import Document, DocumentChunk, RegulationChunk, System

RRF_K = 60
CANDIDATES = 30
RERANK_TOP = 10
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "may",
        "me",
        "my",
        "of",
        "on",
        "or",
        "our",
        "shall",
        "should",
        "so",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "under",
        "us",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "about",
        "any",
        "must",
        "not",
    ]
)

Source = Literal["regulation", "document"]


@dataclass
class Passage:
    id: uuid.UUID
    source: Source
    citation: str
    label: str
    text: str
    score: float
    signals: dict[str, float | int | None] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Filters:
    """All fields are optional and combine with AND. `articles` and `regulation_only` apply to the
    regulation text, `system_id`, `doc_types` and `documents_only` to documents."""

    system_id: uuid.UUID | None = None
    doc_types: tuple[DocumentType, ...] = ()
    articles: tuple[int, ...] = ()
    sources: tuple[Source, ...] = ("regulation", "document")
    # A system owner sees organisation wide documents and those of the systems they own.
    owner_user_id: uuid.UUID | None = None
    include_org_wide: bool = True


class Reranker(Protocol):
    name: str

    def score(self, query: str, passages: list[str]) -> list[float]: ...


class CrossEncoderReranker:
    """Scores (query, passage) pairs jointly. Slower than the bi-encoder, so it only sees the top few."""

    def __init__(
        self, model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2", local_files_only: bool = False
    ) -> None:
        self.name = model
        self._local_only = local_files_only
        self._model: Any = None

    def score(self, query: str, passages: list[str]) -> list[float]:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(
                self.name, device="cpu", max_length=512, local_files_only=self._local_only
            )
        return [float(s) for s in self._model.predict([(query, p) for p in passages])]


def query_terms(query: str) -> list[str]:
    seen: dict[str, None] = {}
    for word in re.findall(r"[a-z0-9]+", query.lower()):
        if len(word) > 2 and word not in STOPWORDS:
            seen.setdefault(word, None)
    return list(seen)


def tsquery_string(query: str) -> str:
    """Terms joined with OR. Only letters and digits survive, so the string is safe to hand to
    to_tsquery. Ranking (ts_rank_cd) rewards passages that match more of the terms."""
    return " | ".join(query_terms(query))


def reciprocal_rank_fusion(rankings: list[list[Any]], k: int = RRF_K) -> dict[Any, float]:
    scores: dict[Any, float] = {}
    for ranking in rankings:
        for position, key in enumerate(ranking, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + position)
    return scores


def regulation_label(article: int, paragraph: str | None, title: str | None) -> str:
    where = f"Article {article}" + (f"({paragraph})" if paragraph else "")
    return f"GDPR {where}" + (f", {title}" if title else "")


def document_label(doc_title: str, heading: str | None, page: int | None) -> str:
    parts = [doc_title]
    if heading:
        parts.append(heading)
    if page:
        parts.append(f"page {page}")
    return ", ".join(parts)


@dataclass
class SearchResult:
    passages: list[Passage]
    timings_ms: dict[str, float]
    reranked: bool


class HybridRetriever:
    def __init__(
        self,
        session: Session,
        embedder: Embedder,
        reranker: Reranker | None = None,
        *,
        candidates: int = CANDIDATES,
        rrf_k: int = RRF_K,
        mode: Literal["hybrid", "vector", "fulltext"] = "hybrid",
    ) -> None:
        self.session = session
        self.embedder = embedder
        self.reranker = reranker
        self.candidates = candidates
        self.rrf_k = rrf_k
        self.mode = mode

    # -- public ------------------------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        filters: Filters | None = None,
        rerank: bool | None = None,
    ) -> SearchResult:
        filters = filters or Filters()
        timings: dict[str, float] = {}
        started = time.perf_counter()
        vector_hits: list[Passage] = []
        text_hits: list[Passage] = []
        if self.mode in ("hybrid", "vector"):
            vector = self.embedder.embed([self._query_text(query)])[0]
            timings["embed"] = _ms(started)
            vector_hits = self._vector(vector, filters)
        terms = tsquery_string(query)
        if self.mode in ("hybrid", "fulltext") and terms:
            text_hits = self._fulltext(terms, filters)
        timings["retrieve"] = _ms(started) - timings.get("embed", 0.0)

        passages = self._fuse(vector_hits, text_hits)
        do_rerank = self.reranker is not None if rerank is None else rerank
        reranked = False
        if do_rerank and self.reranker is not None and passages:
            mark = time.perf_counter()
            passages = self._rerank(query, passages)
            timings["rerank"] = _ms(mark)
            reranked = True
        timings["total"] = _ms(started)
        return SearchResult(passages[:top_k], timings, reranked)

    def resolve_citation(self, citation: str, filters: Filters | None = None) -> Passage | None:
        """The passage a citation points at, or None if it does not exist (or is not visible)."""
        filters = filters or Filters()
        if citation.startswith("reg:"):
            row = self.session.execute(
                select(RegulationChunk).where(RegulationChunk.chunk_key == citation[4:])
            ).scalar_one_or_none()
            return self._regulation_passage(row, 0.0, {}) if row else None
        match = re.fullmatch(r"doc:([0-9a-f-]{36})#(\d+)", citation)
        if not match:
            return None
        stmt = self._document_select(filters).where(
            DocumentChunk.document_id == uuid.UUID(match.group(1)),
            DocumentChunk.chunk_index == int(match.group(2)),
        )
        doc_row = self.session.execute(stmt).first()
        return self._document_passage(doc_row, 0.0, {}) if doc_row else None

    # -- candidate queries -------------------------------------------------------------------

    def _vector(self, vector: list[float], filters: Filters) -> list[Passage]:
        self.session.execute(text("SET LOCAL hnsw.ef_search = 100"))
        found: list[Passage] = []
        if "regulation" in filters.sources and not filters.doc_types and not filters.system_id:
            distance = RegulationChunk.embedding.cosine_distance(vector)
            stmt = (
                select(RegulationChunk, (1 - distance).label("sim"))
                .where(RegulationChunk.embedding.is_not(None))
                .order_by(distance)
                .limit(self.candidates)
            )
            if filters.articles:
                stmt = stmt.where(RegulationChunk.article.in_(filters.articles))
            found += [
                self._regulation_passage(
                    r.RegulationChunk, float(r.sim), {"vector_similarity": float(r.sim)}
                )
                for r in self.session.execute(stmt)
            ]
        if "document" in filters.sources and not filters.articles:
            distance = DocumentChunk.embedding.cosine_distance(vector)
            stmt = (
                self._document_select(filters, extra=(1 - distance).label("sim"))
                .where(DocumentChunk.embedding.is_not(None))
                .order_by(distance)
                .limit(self.candidates)
            )
            found += [
                self._document_passage(r, float(r.sim), {"vector_similarity": float(r.sim)})
                for r in self.session.execute(stmt)
            ]
        found.sort(key=lambda p: p.score, reverse=True)  # cosine is comparable across the tables
        return found[: self.candidates]

    def _fulltext(self, terms: str, filters: Filters) -> list[Passage]:
        found: list[Passage] = []
        if "regulation" in filters.sources and not filters.doc_types and not filters.system_id:
            query = func.to_tsquery("english", terms)
            rank = func.ts_rank_cd(RegulationChunk.tsv, query, 32)
            stmt = (
                select(RegulationChunk, rank.label("rank"))
                .where(RegulationChunk.tsv.op("@@")(query))
                .order_by(rank.desc())
                .limit(self.candidates)
            )
            if filters.articles:
                stmt = stmt.where(RegulationChunk.article.in_(filters.articles))
            found += [
                self._regulation_passage(
                    r.RegulationChunk, float(r.rank), {"fulltext_rank_score": float(r.rank)}
                )
                for r in self.session.execute(stmt)
            ]
        if "document" in filters.sources and not filters.articles:
            query = func.to_tsquery("english", terms)
            rank = func.ts_rank_cd(DocumentChunk.tsv, query, 32)
            stmt = (
                self._document_select(filters, extra=rank.label("rank"))
                .where(DocumentChunk.tsv.op("@@")(query))
                .order_by(rank.desc())
                .limit(self.candidates)
            )
            found += [
                self._document_passage(r, float(r.rank), {"fulltext_rank_score": float(r.rank)})
                for r in self.session.execute(stmt)
            ]
        found.sort(key=lambda p: p.score, reverse=True)
        return found[: self.candidates]

    def _document_select(self, filters: Filters, extra: Any = None) -> Select[Any]:
        columns: list[Any] = [DocumentChunk, Document]
        if extra is not None:
            columns.append(extra)
        stmt = select(*columns).join(Document, Document.id == DocumentChunk.document_id)
        if filters.system_id:
            stmt = stmt.where(DocumentChunk.system_id == filters.system_id)
        if filters.doc_types:
            stmt = stmt.where(Document.doc_type.in_(filters.doc_types))
        if filters.owner_user_id:
            owned = select(System.id).where(System.owner_user_id == filters.owner_user_id)
            if filters.include_org_wide:
                stmt = stmt.where(
                    or_(DocumentChunk.system_id.in_(owned), DocumentChunk.system_id.is_(None))
                )
            else:
                stmt = stmt.where(DocumentChunk.system_id.in_(owned))
        elif not filters.include_org_wide:
            stmt = stmt.where(DocumentChunk.system_id.is_not(None))
        return stmt

    # -- fusion and reranking ----------------------------------------------------------------

    def _fuse(self, vector_hits: list[Passage], text_hits: list[Passage]) -> list[Passage]:
        by_id: dict[uuid.UUID, Passage] = {}
        for hits, signal in ((vector_hits, "vector_rank"), (text_hits, "fulltext_rank")):
            for position, passage in enumerate(hits, start=1):
                known = by_id.setdefault(passage.id, passage)
                known.signals.update(passage.signals)
                known.signals[signal] = position
        scores = reciprocal_rank_fusion(
            [[p.id for p in vector_hits], [p.id for p in text_hits]], self.rrf_k
        )
        for pid, passage in by_id.items():
            passage.score = round(scores[pid], 6)
        return sorted(by_id.values(), key=lambda p: (-p.score, str(p.citation)))

    def _rerank(self, query: str, passages: list[Passage]) -> list[Passage]:
        reranker = self.reranker
        if reranker is None:
            return passages
        head, tail = passages[:RERANK_TOP], passages[RERANK_TOP:]
        scores = reranker.score(query, [_rerank_text(p) for p in head])
        for passage, score in zip(head, scores, strict=True):
            passage.signals["rerank_score"] = round(score, 4)
        head.sort(key=lambda p: -float(p.signals["rerank_score"] or 0.0))
        return head + tail

    def _query_text(self, query: str) -> str:
        return BGE_QUERY_PREFIX + query if "bge" in self.embedder.name.lower() else query

    # -- row to passage ----------------------------------------------------------------------

    @staticmethod
    def _regulation_passage(
        row: RegulationChunk, score: float, signals: dict[str, float | int | None]
    ) -> Passage:
        return Passage(
            id=row.id,
            source="regulation",
            citation=f"reg:{row.chunk_key}",
            label=regulation_label(row.article or 0, row.paragraph, row.title),
            text=row.text,
            score=score,
            signals=dict(signals),
            metadata={
                "regulation": row.regulation,
                "article": row.article,
                "paragraph": row.paragraph,
                "chapter": row.chapter,
                "title": row.title,
            },
        )

    @staticmethod
    def _document_passage(
        row: Any, score: float, signals: dict[str, float | int | None]
    ) -> Passage:
        chunk: DocumentChunk = row.DocumentChunk
        document: Document = row.Document
        return Passage(
            id=chunk.id,
            source="document",
            citation=f"doc:{document.id}#{chunk.chunk_index}",
            label=document_label(document.title, chunk.heading, chunk.page),
            text=chunk.text,
            score=score,
            signals=dict(signals),
            metadata={
                "document_id": str(document.id),
                "doc_type": document.doc_type.value,
                "system_id": str(chunk.system_id) if chunk.system_id else None,
                "heading": chunk.heading,
                "page": chunk.page,
                "chunk_index": chunk.chunk_index,
                "source_uri": document.source_uri,
            },
        )


def _rerank_text(passage: Passage) -> str:
    return f"{passage.label}. {passage.text}"


def _ms(since: float) -> float:
    return round((time.perf_counter() - since) * 1000, 1)


__all__ = [
    "CrossEncoderReranker",
    "Filters",
    "HybridRetriever",
    "Passage",
    "Reranker",
    "SearchResult",
    "reciprocal_rank_fusion",
    "tsquery_string",
]
