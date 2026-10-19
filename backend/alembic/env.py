import os

from sqlalchemy import create_engine, pool

import app.db.models  # noqa: F401  (registers tables on the metadata)
from alembic import context
from app.core.config import get_settings
from app.db.base import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    # Tests and tooling may pass the URL through the alembic config instead.
    configured = config.get_main_option("sqlalchemy.url")
    return (
        configured
        or os.environ.get("MIGRATION_DATABASE_URL")
        or get_settings().migration_database_url
    )


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
