"""A reference estate organisation taken through discovery and classification once per session,
shared by the fusion and record tests."""

import base64
import json
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.classify.embedder import SentenceTransformerEmbedder
from app.core.config import Settings
from app.db.enums import DocumentType, Role
from app.db.session import TenantContext, TenantSession, set_tenant
from app.knowledge.ingest import DocumentIngestor
from app.llm.router import LLMRouter, ProviderLimits
from app.main import create_app
from app.services import provisioning
from tests.fixtures_api import ENCRYPTION_KEY, JWT_SECRET, PASSWORD, client_for, csrf
from tests.llm_support import FakeClock, TaskAwareProvider
from tests.test_discovery_api import create_system, run_discovery, upload_estate_system

DATASETS = Path(__file__).resolve().parents[2] / "datasets"
ESTATE = DATASETS / "estate"
SYSTEM_IDS = sorted(p.name for p in ESTATE.iterdir() if (p / "ground_truth.json").exists())
REFERENCE_DATE = date(2026, 10, 1)


@dataclass
class FusionEstate:
    org_id: uuid.UUID
    app: FastAPI
    admin: TestClient
    systems: dict[str, str]  # estate id -> system uuid
    provider: TaskAwareProvider
    router: LLMRouter
    users: dict[str, Any] = field(default_factory=dict)
    summaries: dict[str, dict[str, Any]] = field(default_factory=dict)

    def findings(self, estate_id: str | None = None, **params: str) -> list[dict[str, Any]]:
        query = dict(params)
        if estate_id:
            query["system_id"] = self.systems[estate_id]
        response = self.admin.get("/api/v1/findings", params={"limit": 1000, **query})
        assert response.status_code == 200, response.text
        return list(response.json())

    def pairs(self) -> set[tuple[str, str]]:
        """(estate system, type) of the open findings of the estate systems (copies made by other
        tests in the same organisation are ignored)."""
        by_uuid = {v: k for k, v in self.systems.items()}
        return {
            (by_uuid[f["system_id"]], f["type"])
            for f in self.findings(status="open")
            if f["system_id"] in by_uuid
        }


def upload_notice_and_questionnaire(client: TestClient, system_id: str, estate_id: str) -> None:
    for kind, name in (("privacy_policy", "policy.md"), ("questionnaire", "questionnaire.json")):
        response = client.post(
            f"/api/v1/systems/{system_id}/evidence",
            data={"kind": kind},
            files={
                "file": (name, (ESTATE / estate_id / name).read_bytes(), "application/octet-stream")
            },
            headers=csrf(client),
        )
        assert response.status_code == 201, (kind, response.text)


@pytest.fixture(scope="session")
def fusion_estate(
    owner_engine: Engine,
    session_factory: sessionmaker[TenantSession],
    real_embedder: SentenceTransformerEmbedder,
    taxonomy_index: int,
    regulation_index: int,
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[FusionEstate]:
    base = tmp_path_factory.mktemp("fusion")
    org_id = provisioning.create_organization(
        owner_engine, "Northbridge", f"nb-{uuid.uuid4().hex[:8]}"
    )
    settings = Settings(
        jwt_secret=SecretStr(JWT_SECRET),
        evidence_encryption_key=SecretStr(ENCRYPTION_KEY),
        upload_dir=str(base / "evidence"),
        login_rate_limit="1000/minute",
        default_rate_limit="100000/minute",
        max_upload_bytes=2_000_000,
        rea_enabled=False,
        rea_input_dir=str(base / "stage"),
        embedding_local_files_only=True,
        reference_date=REFERENCE_DATE,
        celery_eager=True,
        leads_org_id=org_id,
        cors_allowed_origins=["https://app.example.test"],
        observation_allowed_hosts=["127.0.0.1"],
    )
    provider = TaskAwareProvider(
        verdict="undetermined"
    )  # a scripted model that never overrules the rules
    clock = FakeClock()
    router = LLMRouter(
        {"groq": provider}, lambda: session_factory, clock=clock, sleep=clock.sleep,
        limits={"groq": ProviderLimits(10_000_000, 10_000)},
    )  # fmt: skip
    app = create_app(settings, session_factory, embedder=real_embedder, llm_router=router)

    users = {
        role.value: provisioning.create_user(
            owner_engine, org_id, f"{role.value}-{uuid.uuid4().hex[:6]}@nb.example", role.value.title(), PASSWORD, role
        )
        for role in Role
    }  # fmt: skip
    admin = client_for(app, users["admin"])

    # organisation wide documents: the company policy and the vendor agreements
    with session_factory() as db:
        set_tenant(db, TenantContext(org_id=org_id))
        ingestor = DocumentIngestor(db, real_embedder)
        company = DATASETS / "policies" / "company_privacy_policy.md"
        ingestor.ingest(
            filename=company.name, content=company.read_bytes(), doc_type=DocumentType.POLICY,
            source_uri="policies/company_privacy_policy.md",
        )  # fmt: skip
        for agreement in sorted((DATASETS / "policies" / "vendor_agreements").glob("*.md")):
            ingestor.ingest(
                filename=agreement.name, content=agreement.read_bytes(),
                doc_type=DocumentType.VENDOR_AGREEMENT, source_uri=f"policies/vendor_agreements/{agreement.name}",
            )  # fmt: skip
        db.commit()

    systems: dict[str, str] = {}
    summaries: dict[str, dict[str, Any]] = {}
    for estate_id in SYSTEM_IDS:
        system_id = create_system(admin, estate_id, owner=users["system_owner"].id)
        upload_estate_system(admin, system_id, estate_id)
        upload_notice_and_questionnaire(admin, system_id, estate_id)
        run_discovery(admin, system_id)
        classified = admin.post(f"/api/v1/systems/{system_id}/classification", headers=csrf(admin))
        assert classified.status_code == 200, classified.text
        fused = admin.post(f"/api/v1/systems/{system_id}/fusion", headers=csrf(admin))
        assert fused.status_code == 200, fused.text
        systems[estate_id] = system_id
        summaries[estate_id] = fused.json()
    yield FusionEstate(org_id, app, admin, systems, provider, router, users, summaries)


Factory = Callable[[Settings], FastAPI]
__all__ = ["FusionEstate", "fusion_estate", "base64", "json"]


@pytest.fixture(scope="session")
def estate_generation(fusion_estate: FusionEstate) -> dict[str, dict[str, Any]]:
    """The answer of the first record generation of every estate system."""
    admin = fusion_estate.admin
    out = {}
    for estate_id, system_id in fusion_estate.systems.items():
        response = admin.post(f"/api/v1/systems/{system_id}/record", headers=csrf(admin))
        assert response.status_code == 200, response.text
        out[estate_id] = response.json()
    return out


@pytest.fixture(scope="session")
def estate_records(estate_generation: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The generated record of every estate system."""
    return {k: v["activity"] for k, v in estate_generation.items()}
