"""Text embeddings. Production uses BAAI/bge-small-en-v1.5 (384 dimensions, MIT) on the CPU
through sentence-transformers; the model is downloaded once (scripts/download_embedding_model.py)
and baked into the image. Tests that do not need meaning use HashingEmbedder."""

import hashlib
import math
import re
from typing import Any, Protocol

DIMENSIONS = 384
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"


class Embedder(Protocol):
    name: str
    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class SentenceTransformerEmbedder:
    """Loads the model on first use. Vectors are L2 normalised, so cosine similarity is a dot product."""

    def __init__(self, model: str = DEFAULT_MODEL, local_files_only: bool = False) -> None:
        self.name = model
        self.dimensions = DIMENSIONS
        self._local_only = local_files_only
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # heavy import, only when needed

            self._model = SentenceTransformer(
                self.name, device="cpu", local_files_only=self._local_only
            )
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._load().encode(
            texts, normalize_embeddings=True, batch_size=64, show_progress_bar=False
        )
        return [[float(x) for x in v] for v in vectors]


class HashingEmbedder:
    """Deterministic bag of word embedding for tests and offline runs. It captures shared words,
    not meaning, and is never used to classify real systems."""

    name = "hashing-384"
    dimensions = DIMENSIONS

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            digest = hashlib.sha256(word.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[index] += 1.0 if digest[4] % 2 else -1.0
            vector[(index + 7) % self.dimensions] += 0.5
        norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        return [x / norm for x in vector]
