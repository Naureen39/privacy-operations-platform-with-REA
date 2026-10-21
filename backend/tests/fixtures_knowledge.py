"""Fixtures for knowledge base tests: the regulation text and the estate documents, embedded with
the real model (skipped when it is not available offline)."""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.classify.embedder import SentenceTransformerEmbedder
from app.db.models import System
from app.db.session import TenantContext, TenantSession, set_tenant
from app.knowledge.evaluation import ingest_reference_documents, reference_documents
from app.knowledge.ingest import load_regulation
from app.knowledge.retrieval import CrossEncoderReranker
from app.services import provisioning


@pytest.fixture(scope="session")
def regulation_index(owner_engine: Engine, real_embedder: SentenceTransformerEmbedder) -> int:
    return load_regulation(owner_engine, real_embedder)


@dataclass
class KnowledgeOrg:
    org_id: uuid.UUID
    system_ids: dict[str, uuid.UUID]
    chunks: int


@pytest.fixture(scope="session")
def knowledge_org(
    owner_engine: Engine,
    session_factory: sessionmaker[TenantSession],
    real_embedder: SentenceTransformerEmbedder,
    regulation_index: int,
) -> Iterator[KnowledgeOrg]:
    """One organisation with a system per estate system and every estate document indexed."""
    slug = f"kb-{uuid.uuid4().hex[:8]}"
    org_id = provisioning.create_organization(owner_engine, "Knowledge Org", slug)
    keys = sorted({d.system_key for d in reference_documents() if d.system_key})
    with session_factory() as db:
        set_tenant(db, TenantContext(org_id=org_id))
        systems = {key: System(org_id=org_id, name=key, slug=key.replace("_", "-")) for key in keys}
        db.add_all(systems.values())
        db.flush()
        system_ids = {key: system.id for key, system in systems.items()}
        chunks = ingest_reference_documents(db, real_embedder, system_ids)
        db.commit()
    yield KnowledgeOrg(org_id, system_ids, chunks)


@pytest.fixture(scope="session")
def real_reranker() -> CrossEncoderReranker:
    reranker = CrossEncoderReranker(local_files_only=True)
    try:
        reranker.score("probe", ["probe"])
    except Exception as exc:
        pytest.skip(f"cross encoder not available offline ({type(exc).__name__})")
    return reranker
