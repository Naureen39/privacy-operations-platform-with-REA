"""API level fixtures, registered through conftest's pytest_plugins."""

import base64
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.enums import Role
from app.db.session import TenantSession
from app.main import create_app
from app.services import provisioning

PASSWORD = "Correct-Horse-Battery-1"
JWT_SECRET = "test-secret-" + "x" * 40
ENCRYPTION_KEY = base64.b64encode(b"k" * 32).decode()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        jwt_secret=SecretStr(JWT_SECRET),
        evidence_encryption_key=SecretStr(ENCRYPTION_KEY),
        upload_dir=str(tmp_path / "evidence"),
        login_rate_limit="1000/minute",
        default_rate_limit="10000/minute",
        max_upload_bytes=200_000,
        cors_allowed_origins=["https://app.example.test"],
        observation_allowed_hosts=[
            "93.184.216.34",
            "127.0.0.1",
            "169.254.169.254",
            "10.0.0.5",
        ],
    )


@pytest.fixture
def make_app(
    session_factory: sessionmaker[TenantSession],
) -> Callable[[Settings], FastAPI]:
    return lambda s: create_app(s, session_factory)


@pytest.fixture
def app(settings: Settings, make_app: Callable[[Settings], FastAPI]) -> FastAPI:
    return make_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, base_url="https://testserver") as c:
        yield c


class Org:
    def __init__(self, org_id: uuid.UUID, slug: str) -> None:
        self.id = org_id
        self.slug = slug
        self.users: dict[str, provisioning.ProvisionedUser] = {}


@pytest.fixture
def org(owner_engine: Engine) -> Org:
    """A fresh organization with one account per role."""
    slug = f"acme-{uuid.uuid4().hex[:8]}"
    org_id = provisioning.create_organization(owner_engine, "Acme", slug)
    result = Org(org_id, slug)
    for role in Role:
        email = f"{role.value}-{uuid.uuid4().hex[:8]}@acme.example"
        result.users[role.value] = provisioning.create_user(
            owner_engine, org_id, email, role.value.title(), PASSWORD, role
        )
    return result


@pytest.fixture
def other_org(owner_engine: Engine) -> Org:
    slug = f"globex-{uuid.uuid4().hex[:8]}"
    org_id = provisioning.create_organization(owner_engine, "Globex", slug)
    result = Org(org_id, slug)
    email = f"admin-{uuid.uuid4().hex[:8]}@globex.example"
    result.users["admin"] = provisioning.create_user(
        owner_engine, org_id, email, "Globex Admin", PASSWORD, Role.ADMIN
    )
    return result


def login(client: TestClient, email: str, password: str = PASSWORD, org_id: object = None):  # type: ignore[no-untyped-def]
    body: dict[str, object] = {"email": email, "password": password}
    if org_id is not None:
        body["org_id"] = str(org_id)
    return client.post("/api/v1/auth/login", json=body)


def csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("pl_csrf") or ""}


def client_for(app: FastAPI, user: provisioning.ProvisionedUser) -> TestClient:
    c = TestClient(app, base_url="https://testserver")
    response = login(c, user.email)
    assert response.status_code == 200, response.text
    return c
