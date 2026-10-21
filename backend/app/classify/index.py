"""The embedded taxonomy: building it, loading it into PostgreSQL (pgvector) and querying it.

Each category contributes its label, its definition and every synonym as a short phrase. An
element is matched by embedding its description and taking the nearest entries; the best entry
per category is that category's similarity.
"""

import math
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from app.classify.embedder import Embedder
from app.classify.knowledge import Knowledge
from app.classify.normalize import expand, split_identifier
from app.db.models import TaxonomyEntry

TOP_K = 14


@dataclass(frozen=True)
class EntrySpec:
    category_id: str
    kind: str  # label | definition | synonym
    text: str
    special_category: bool


@dataclass(frozen=True)
class Match:
    category_id: str
    kind: str
    text: str
    similarity: float


class Matcher(Protocol):
    def top(self, vectors: list[list[float]], k: int = TOP_K) -> list[list[Match]]: ...


def build_entries(knowledge: Knowledge) -> list[EntrySpec]:
    entries: list[EntrySpec] = []
    for category in knowledge.categories.values():
        entries.append(EntrySpec(category.id, "label", category.label, category.special_category))
        entries.append(
            EntrySpec(
                category.id,
                "definition",
                f"{category.label}: {category.definition}",
                category.special_category,
            )
        )
        seen: set[str] = set()
        for synonym in category.synonyms:
            words = " ".join(expand(split_identifier(synonym)))
            if words and words not in seen:
                seen.add(words)
                entries.append(EntrySpec(category.id, "synonym", words, category.special_category))
    return entries


def load_index(
    engine: Engine, knowledge: Knowledge, embedder: Embedder, force: bool = False
) -> int:
    """(Re)load the taxonomy entries with the owner role. Skips work when the stored version matches."""
    version = f"{knowledge.version}-{embedder.name.split('/')[-1]}"[:32]
    with engine.begin() as conn:
        session = Session(bind=conn)
        stored = session.scalars(select(TaxonomyEntry.source_version).distinct()).all()
        if not force and stored == [version]:
            return int(session.scalar(select(func.count()).select_from(TaxonomyEntry)) or 0)
        entries = build_entries(knowledge)
        vectors = embedder.embed([e.text for e in entries])
        session.execute(delete(TaxonomyEntry))
        session.add_all(
            TaxonomyEntry(
                category_id=e.category_id, kind=e.kind, text=e.text, special_category=e.special_category,
                source_version=version, embedding=v,
            )
            for e, v in zip(entries, vectors, strict=True)
        )  # fmt: skip
        session.flush()
        return len(entries)


class PgMatcher:
    """Nearest taxonomy entries by cosine distance, using the pgvector HNSW index."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def top(self, vectors: list[list[float]], k: int = TOP_K) -> list[list[Match]]:
        results: list[list[Match]] = []
        for vector in vectors:
            distance = TaxonomyEntry.embedding.cosine_distance(vector)
            rows = self.session.execute(
                select(
                    TaxonomyEntry.category_id,
                    TaxonomyEntry.kind,
                    TaxonomyEntry.text,
                    (1 - distance).label("similarity"),
                )
                .order_by(distance)
                .limit(k)
            ).all()
            results.append(
                [Match(r.category_id, r.kind, r.text, float(r.similarity)) for r in rows]
            )
        return results


class MemoryMatcher:
    """The same lookup computed in memory (used to tune thresholds and in tests)."""

    def __init__(self, knowledge: Knowledge, embedder: Embedder) -> None:
        self.entries = build_entries(knowledge)
        self.vectors = embedder.embed([e.text for e in self.entries])

    def top(self, vectors: list[list[float]], k: int = TOP_K) -> list[list[Match]]:
        out: list[list[Match]] = []
        for vector in vectors:
            scored = sorted(
                ((_cosine(vector, v), e) for v, e in zip(self.vectors, self.entries, strict=True)),
                key=lambda pair: pair[0],
                reverse=True,
            )[:k]
            out.append([Match(e.category_id, e.kind, e.text, sim) for sim, e in scored])
        return out


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def category_scores(matches: list[Match]) -> list[tuple[str, float]]:
    """Best similarity per category, highest first."""
    best: dict[str, float] = {}
    for match in matches:
        best[match.category_id] = max(best.get(match.category_id, -1.0), match.similarity)
    return sorted(best.items(), key=lambda item: item[1], reverse=True)
