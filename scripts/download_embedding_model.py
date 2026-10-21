"""Download the embedding model so that classification works offline (and so it can be baked into
an image: run this during the image build and set EMBEDDING_LOCAL_FILES_ONLY=true at run time).

    cd backend && uv run python ../scripts/download_embedding_model.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.classify.embedder import SentenceTransformerEmbedder  # noqa: E402
from app.core.config import get_settings  # noqa: E402


def main() -> None:
    embedder = SentenceTransformerEmbedder(get_settings().embedding_model)
    vector = embedder.embed(["date of birth"])[0]
    print(f"model {embedder.name} ready, {len(vector)} dimensions")


if __name__ == "__main__":
    main()
