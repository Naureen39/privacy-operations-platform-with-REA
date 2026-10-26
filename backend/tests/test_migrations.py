from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL

from alembic import command
from app.db.base import Base
from app.db.models import *  # noqa: F403  (register tables)
from tests.conftest import alembic_config, create_database


def _tables(url: URL) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()


def test_upgrade_downgrade_upgrade(admin_url: URL) -> None:
    url = create_database(admin_url, "migration_cycle")
    config = alembic_config(url.render_as_string(hide_password=False))
    expected = set(Base.metadata.tables)

    command.upgrade(config, "head")
    assert _tables(url) == expected

    command.downgrade(config, "0001")  # removes the security objects, auth columns and later tables
    assert _tables(url) == expected - {
        "taxonomy_entries",
        "dpia_screenings",
        "jobs",
        "job_events",
        "notifications",
    }
    engine = create_engine(url)
    with engine.connect() as conn:
        rls_on = conn.execute(
            text("SELECT count(*) FROM pg_class WHERE relrowsecurity AND relkind = 'r'")
        ).scalar_one()
        assert rls_on == 0
    engine.dispose()

    command.downgrade(config, "base")
    assert _tables(url) == set()
    engine = create_engine(url)
    with engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM pg_extension WHERE extname='vector'")
            ).scalar_one()
            == 0
        )
    engine.dispose()

    command.upgrade(config, "head")
    assert _tables(url) == expected


def test_models_match_migrations(owner_url: URL) -> None:
    """The migrated schema has no drift from the declared models."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    engine = create_engine(owner_url)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        diff = compare_metadata(ctx, Base.metadata)
    engine.dispose()
    assert diff == []


def test_vector_and_search_indexes_exist(owner_url: URL) -> None:
    engine = create_engine(owner_url)
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'")
        ).all()
    engine.dispose()
    defs = {name: definition for name, definition in rows}
    for table in ("data_elements", "document_chunks", "regulation_chunks"):
        definition = defs[f"ix_{table}_embedding_hnsw"]
        assert "USING hnsw" in definition and "vector_cosine_ops" in definition
    for table in ("document_chunks", "regulation_chunks"):
        assert "USING gin" in defs[f"ix_{table}_tsv"]
