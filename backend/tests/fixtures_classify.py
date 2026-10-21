"""Fixtures for tests that use the real embedding model (skipped when it is not available offline)."""

from functools import lru_cache

import pytest
from sqlalchemy import Engine

from app.classify.embedder import SentenceTransformerEmbedder
from app.classify.index import load_index
from app.classify.knowledge import default_knowledge


@lru_cache
def model_unavailable_reason() -> str | None:
    try:
        SentenceTransformerEmbedder(local_files_only=True).embed(["probe"])
    except Exception as exc:  # any failure to load means the model is not usable here
        return f"embedding model not available offline ({type(exc).__name__}); run scripts/download_embedding_model.py"
    return None


@pytest.fixture(scope="session")
def real_embedder() -> SentenceTransformerEmbedder:
    reason = model_unavailable_reason()
    if reason:
        pytest.skip(reason)
    return SentenceTransformerEmbedder(local_files_only=True)


@pytest.fixture(scope="session")
def taxonomy_index(owner_engine: Engine, real_embedder: SentenceTransformerEmbedder) -> int:
    return load_index(owner_engine, default_knowledge(), real_embedder)
