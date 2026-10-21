"""Embed the GDPR text and load it into PostgreSQL (table regulation_chunks).

    cd backend && uv run python ../scripts/ingest_regulation.py [--force]

Uses the owner connection (the application role can only read the table). Loading is skipped
when the text and the embedding model are unchanged. Run scripts/download_embedding_model.py first
if the model is not cached.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import create_engine  # noqa: E402

from app.classify.embedder import SentenceTransformerEmbedder  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.knowledge.ingest import REGULATION_FILE, load_regulation  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="re-embed even if nothing changed")
    parser.add_argument("--file", type=Path, default=REGULATION_FILE)
    args = parser.parse_args()
    settings = get_settings()
    embedder = SentenceTransformerEmbedder(
        settings.embedding_model, settings.embedding_local_files_only
    )
    engine = create_engine(settings.migration_database_url)
    count = load_regulation(engine, embedder, args.file, force=args.force)
    print(f"regulation index ready: {count} chunks (model {embedder.name})")


if __name__ == "__main__":
    main()
