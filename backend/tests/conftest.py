import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import sessionmaker
from testcontainers.community.postgres import PostgresContainer

from alembic import command
from app.db.session import TenantSession, make_engine, make_session_factory

BACKEND_DIR = Path(__file__).resolve().parent.parent
APP_ROLE = "processledger_app"
APP_PASSWORD = "test_app_password"
IMAGE = "pgvector/pgvector:pg16"


def alembic_config(url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def app_url(owner_url: URL) -> URL:
    return owner_url.set(username=APP_ROLE, password=APP_PASSWORD)


@pytest.fixture(scope="session")
def postgres() -> Iterator[PostgresContainer]:
    os.environ["APP_DB_PASSWORD"] = APP_PASSWORD
    with PostgresContainer(
        IMAGE, username="processledger", dbname="postgres", driver="psycopg"
    ) as pg:
        yield pg


@pytest.fixture(scope="session")
def admin_url(postgres: PostgresContainer) -> URL:
    return make_url(postgres.get_connection_url())


def create_database(admin_url: URL, name: str) -> URL:
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    engine.dispose()
    return admin_url.set(database=name)


@pytest.fixture(scope="session")
def owner_url(admin_url: URL) -> URL:
    """A migrated database, shared by all isolation tests."""
    url = create_database(admin_url, "tenancy")
    command.upgrade(alembic_config(url.render_as_string(hide_password=False)), "head")
    return url


@pytest.fixture(scope="session")
def owner_engine(owner_url: URL) -> Iterator[Engine]:
    engine = create_engine(owner_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def app_engine(owner_url: URL) -> Iterator[Engine]:
    engine = make_engine(app_url(owner_url).render_as_string(hide_password=False), pool_size=3)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def session_factory(app_engine: Engine) -> sessionmaker[TenantSession]:
    return make_session_factory(app_engine)


class OrgFixture:
    def __init__(self, org_id: uuid.UUID, slug: str) -> None:
        self.id = org_id
        self.slug = slug


@pytest.fixture
def two_orgs(owner_engine: Engine) -> Iterator[tuple[OrgFixture, OrgFixture]]:
    """Two organizations created by the owner role (the application role cannot do this)."""
    orgs: list[OrgFixture] = []
    with owner_engine.begin() as conn:
        for label in ("a", "b"):
            slug = f"org-{label}-{uuid.uuid4().hex[:8]}"
            org_id = conn.execute(
                text("INSERT INTO organizations (name, slug) VALUES (:n, :s) RETURNING id"),
                {"n": f"Org {label.upper()}", "s": slug},
            ).scalar_one()
            orgs.append(OrgFixture(org_id, slug))
    yield orgs[0], orgs[1]
    with owner_engine.begin() as conn:
        for org in orgs:
            conn.execute(text("DELETE FROM organizations WHERE id = :i"), {"i": org.id})
