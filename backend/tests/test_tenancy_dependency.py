import uuid
from typing import Any

import httpx
import pytest
from fastapi import Depends, FastAPI, Request
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api.tenancy import get_tenant_db
from app.db.models import System
from app.db.session import TenantContext, TenantSession
from tests.conftest import OrgFixture


def build_app(factory: sessionmaker[TenantSession]) -> FastAPI:
    app = FastAPI()
    app.state.session_factory = factory

    @app.middleware("http")
    async def stub_authentication(request: Request, call_next: Any) -> Any:
        # Stands in for Phase 2: derives the tenant from a header the real code will
        # replace with a verified access token.
        org = request.headers.get("x-test-org")
        if org:
            request.state.tenant = TenantContext(uuid.UUID(org))
        return await call_next(request)

    @app.get("/systems")
    def list_systems(db: TenantSession = Depends(get_tenant_db)) -> list[str]:
        return [s.name for s in db.scalars(select(System))]

    @app.post("/systems/{slug}")
    def create_system(slug: str, db: TenantSession = Depends(get_tenant_db)) -> dict[str, str]:
        db.add(System(name=slug.title(), slug=slug))
        return {"slug": slug}

    return app


@pytest.mark.anyio
async def test_dependency_scopes_each_request_to_its_tenant(
    session_factory: sessionmaker[TenantSession],
    two_orgs: tuple[OrgFixture, OrgFixture],
) -> None:
    org_a, org_b = two_orgs
    transport = httpx.ASGITransport(app=build_app(session_factory))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (
            await client.post("/systems/alpha", headers={"x-test-org": str(org_a.id)})
        ).status_code == 200
        assert (
            await client.post("/systems/beta", headers={"x-test-org": str(org_b.id)})
        ).status_code == 200
        a = await client.get("/systems", headers={"x-test-org": str(org_a.id)})
        b = await client.get("/systems", headers={"x-test-org": str(org_b.id)})
    assert a.json() == ["Alpha"]
    assert b.json() == ["Beta"]


@pytest.mark.anyio
async def test_request_without_tenant_is_rejected(
    session_factory: sessionmaker[TenantSession],
) -> None:
    transport = httpx.ASGITransport(app=build_app(session_factory))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/systems")
    assert response.status_code == 401


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
