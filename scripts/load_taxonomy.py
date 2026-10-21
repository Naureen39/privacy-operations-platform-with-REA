"""Embed the personal data taxonomy and load it into PostgreSQL (table taxonomy_entries).

    cd backend && uv run python ../scripts/load_taxonomy.py [--force]

Uses the owner connection (the application role can only read the table). The embedding model is
downloaded on first use; scripts/download_embedding_model.py fetches it ahead of time. Loading is
skipped when the stored version already matches the taxonomy files and the model.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import create_engine  # noqa: E402

from app.classify.embedder import SentenceTransformerEmbedder  # noqa: E402
from app.classify.index import load_index  # noqa: E402
from app.classify.knowledge import load_knowledge  # noqa: E402
from app.core.config import get_settings  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--force", action="store_true", help="reload even if the stored version matches"
    )
    args = parser.parse_args()
    settings = get_settings()
    knowledge = load_knowledge(Path(settings.knowledge_dir) if settings.knowledge_dir else None)
    embedder = SentenceTransformerEmbedder(
        settings.embedding_model, settings.embedding_local_files_only
    )
    engine = create_engine(settings.migration_database_url)
    count = load_index(engine, knowledge, embedder, force=args.force)
    print(
        f"taxonomy index ready: {count} entries (model {embedder.name}, version {knowledge.version})"
    )


if __name__ == "__main__":
    main()
