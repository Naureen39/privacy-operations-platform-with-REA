"""What a worker needs to run a stage: the same pieces the API holds in `app.state`."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import sessionmaker

from app.classify.embedder import Embedder, SentenceTransformerEmbedder
from app.classify.knowledge import Knowledge, load_knowledge
from app.core.config import Settings, get_settings
from app.db.session import TenantSession, make_engine, make_session_factory
from app.discovery.executor import Executor, build_rea_clients
from app.llm.factory import build_router
from app.llm.router import LLMRouter
from app.services.evidence_store import EvidenceStore


@dataclass
class Runtime:
    settings: Settings
    session_factory: sessionmaker[TenantSession]
    knowledge: Knowledge
    embedder: Embedder
    evidence_store: EvidenceStore
    discovery_executor: Executor
    llm_router: LLMRouter


_runtime: Runtime | None = None


def build_runtime(settings: Settings | None = None) -> Runtime:
    from pathlib import Path

    settings = settings or get_settings()
    factory = make_session_factory(make_engine())
    holder: dict[str, Any] = {}
    runtime = Runtime(
        settings=settings,
        session_factory=factory,
        knowledge=load_knowledge(Path(settings.knowledge_dir) if settings.knowledge_dir else None),
        embedder=SentenceTransformerEmbedder(
            settings.embedding_model, settings.embedding_local_files_only
        ),
        evidence_store=EvidenceStore(Path(settings.upload_dir), settings.encryption_key_bytes()),
        discovery_executor=Executor(settings, build_rea_clients(settings)),
        llm_router=build_router(settings, lambda: holder["factory"]),
    )
    holder["factory"] = factory
    return runtime


def runtime_from_state(state: Any, session_factory: sessionmaker[TenantSession]) -> Runtime:
    """The runtime of a running API process (used when tasks run inside it)."""
    return Runtime(
        settings=state.settings,
        session_factory=session_factory,
        knowledge=state.knowledge,
        embedder=state.embedder,
        evidence_store=state.evidence_store,
        discovery_executor=state.discovery_executor,
        llm_router=state.llm_router,
    )


def get_runtime() -> Runtime:
    global _runtime
    if _runtime is None:
        _runtime = build_runtime()
    return _runtime


def set_runtime(runtime: Runtime | None) -> None:
    global _runtime
    _runtime = runtime
