from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.api.deps import CSRF_HEADER
from app.api.middleware import csrf_protection, security_headers
from app.api.routes import (
    admin,
    auth,
    classification,
    discovery,
    evidence,
    fusion,
    knowledge,
    llm,
    records,
    systems,
)
from app.classify.embedder import Embedder, SentenceTransformerEmbedder
from app.classify.knowledge import load_knowledge
from app.core.config import Settings, get_settings
from app.db.session import TenantSession, make_engine, make_session_factory
from app.discovery.executor import Executor, build_rea_clients
from app.knowledge.retrieval import CrossEncoderReranker
from app.llm.factory import build_router
from app.llm.router import LLMRouter
from app.services.evidence_store import EvidenceStore


def create_app(
    settings: Settings | None = None,
    session_factory: sessionmaker[TenantSession] | None = None,
    embedder: Embedder | None = None,
    llm_router: LLMRouter | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    settings.require_secrets()
    limiter = Limiter(key_func=get_remote_address, default_limits=[settings.default_rate_limit])

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = None
        if session_factory is None:
            engine = make_engine(settings.database_url, pool_size=settings.db_pool_size)
            app.state.session_factory = make_session_factory(engine)
        yield
        if engine is not None:
            engine.dispose()

    app = FastAPI(title="ProcessLedger API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.limiter = limiter
    app.state.evidence_store = EvidenceStore(
        Path(settings.upload_dir), settings.encryption_key_bytes()
    )
    app.state.discovery_executor = Executor(settings, build_rea_clients(settings))
    app.state.knowledge = load_knowledge(
        Path(settings.knowledge_dir) if settings.knowledge_dir else None
    )
    app.state.embedder = embedder or SentenceTransformerEmbedder(
        settings.embedding_model, settings.embedding_local_files_only
    )
    app.state.llm_router = llm_router or build_router(settings, lambda: app.state.session_factory)
    app.state.reranker = (
        CrossEncoderReranker(settings.rerank_model, settings.embedding_local_files_only)
        if settings.rerank_enabled
        else None
    )
    if session_factory is not None:
        app.state.session_factory = session_factory

    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

    # Added innermost first: security headers wrap CSRF, CORS wraps everything.
    app.add_middleware(SlowAPIMiddleware)
    app.middleware("http")(csrf_protection)
    app.middleware("http")(security_headers)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", CSRF_HEADER],
        max_age=600,
    )

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", tags=["health"])
    def ready(request: Request) -> dict[str, str]:
        with request.app.state.session_factory() as session:
            session.execute(text("SELECT 1"))
        return {"status": "ready"}

    app.include_router(auth.build_router(limiter, settings))
    app.include_router(systems.router)
    app.include_router(evidence.router)
    app.include_router(discovery.router)
    app.include_router(classification.router)
    app.include_router(fusion.router)
    app.include_router(knowledge.router)
    app.include_router(llm.router)
    app.include_router(records.router)
    app.include_router(admin.router)
    return app
