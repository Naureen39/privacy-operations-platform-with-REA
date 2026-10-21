"""Knowledge base through the API: search, citations, uploads, system ingestion, scoping."""

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.classify.embedder import SentenceTransformerEmbedder
from app.core.config import Settings
from app.db.session import TenantSession
from app.main import create_app
from tests.fixtures_api import Org, client_for, csrf

POLICY = (
    b"# Privacy notice: Kiosk\n\n## Who we share it with\n\n"
    b"We share order data with Zebrafish Logistics for parcel delivery.\n\n"
    b"## How long we keep it\n\nOrders are kept for 18 months.\n"
)


@pytest.fixture
def kapp(
    settings: Settings,
    session_factory: sessionmaker[TenantSession],
    real_embedder: SentenceTransformerEmbedder,
    regulation_index: int,
    tmp_path: Path,
) -> FastAPI:
    return create_app(
        settings.model_copy(update={"rea_enabled": False}),
        session_factory,
        embedder=real_embedder,
    )


def mk_system(admin: TestClient, name: str, owner: object = None) -> str:
    body: dict[str, Any] = {"name": name}
    if owner:
        body["owner_user_id"] = str(owner)
    response = admin.post("/api/v1/systems", json=body, headers=csrf(admin))
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def search(c: TestClient, query: str, **extra: Any) -> dict[str, Any]:
    response = c.post("/api/v1/knowledge/search", json={"query": query, **extra}, headers=csrf(c))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def upload(c: TestClient, content: bytes = POLICY, name: str = "notice.md", **data: str) -> Any:
    return c.post(
        "/api/v1/knowledge/documents",
        data={"doc_type": "policy", **data},
        files={"file": (name, content, "text/markdown")},
        headers=csrf(c),
    )


def test_search_returns_regulation_passages_with_ids_and_citations(kapp: FastAPI, org: Org) -> None:
    c = client_for(kapp, org.users["viewer"])
    body = search(c, "When must a personal data breach be reported to the authority?", top_k=3)
    assert body["reranked"] is False and set(body["timings_ms"]) >= {"total", "retrieve", "embed"}
    top = body["passages"][0]
    assert top["source"] == "regulation" and top["metadata"]["article"] == 33
    assert (
        top["citation"].startswith("reg:gdpr-art33")
        and top["id"]
        and top["label"].startswith("GDPR Article 33")
    )
    assert len(body["passages"]) == 3

    resolved = c.get("/api/v1/knowledge/passage", params={"citation": top["citation"]})
    assert resolved.status_code == 200 and resolved.json()["id"] == top["id"]
    assert c.get("/api/v1/knowledge/passage", params={"citation": "reg:nope"}).status_code == 404


def test_article_filter_and_input_validation(kapp: FastAPI, org: Org) -> None:
    c = client_for(kapp, org.users["analyst"])
    body = search(c, "what must the controller do", articles=[30], sources=["regulation"])
    assert {p["metadata"]["article"] for p in body["passages"]} == {30}
    for bad in ({"query": "ab"}, {"query": "x" * 1001}, {"query": "valid query", "top_k": 99},
                {"query": "valid query", "sources": ["web"]}, {"query": "valid query", "doc_types": ["nope"]}):  # fmt: skip
        assert c.post("/api/v1/knowledge/search", json=bad, headers=csrf(c)).status_code == 422


def test_search_requires_login_and_csrf(kapp: FastAPI, org: Org) -> None:
    anonymous = TestClient(kapp, base_url="https://testserver")
    assert anonymous.post("/api/v1/knowledge/search", json={"query": "breach"}).status_code in (
        401,
        403,
    )
    c = client_for(kapp, org.users["viewer"])
    assert (
        c.post("/api/v1/knowledge/search", json={"query": "breach"}).status_code == 403
    )  # no CSRF token


def test_uploaded_document_is_searchable_by_its_own_organisation_only(
    kapp: FastAPI, org: Org, other_org: Org
) -> None:
    admin = client_for(kapp, org.users["admin"])
    created = upload(admin, title="Kiosk notice")
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "created" and created.json()["chunks"] == 2

    body = search(admin, "Which company delivers parcels?", sources=["document"])
    top = body["passages"][0]
    assert top["metadata"]["heading"] == "Who we share it with" and "Zebrafish" in top["text"]
    assert top["citation"] == f"doc:{created.json()['document_id']}#0"
    assert top["label"] == "Kiosk notice, Who we share it with"

    stranger = client_for(kapp, other_org.users["admin"])
    leaked = search(stranger, "Which company delivers parcels?", sources=["document"])
    assert all("Zebrafish" not in p["text"] for p in leaked["passages"])
    assert (
        stranger.get("/api/v1/knowledge/passage", params={"citation": top["citation"]}).status_code
        == 404
    )
    assert (
        stranger.delete(
            f"/api/v1/knowledge/documents/{created.json()['document_id']}", headers=csrf(stranger)
        ).status_code
        == 404
    )


def test_upload_is_idempotent_listed_and_deletable(kapp: FastAPI, org: Org) -> None:
    admin = client_for(kapp, org.users["admin"])
    first = upload(admin, title="Notice").json()
    again = upload(admin, title="Notice").json()
    assert again["status"] == "unchanged" and again["document_id"] == first["document_id"]
    changed = upload(admin, content=POLICY.replace(b"18", b"24"), title="Notice").json()
    assert changed["status"] == "replaced"

    listed = admin.get("/api/v1/knowledge/documents", params={"doc_type": "policy"}).json()
    assert [d["id"] for d in listed] == [changed["document_id"]] and listed[0]["chunks"] == 2

    assert (
        admin.delete(
            f"/api/v1/knowledge/documents/{changed['document_id']}", headers=csrf(admin)
        ).status_code
        == 204
    )
    assert admin.get("/api/v1/knowledge/documents").json() == []
    audit = admin.get("/api/v1/audit-log").json()
    actions = {entry["action"] for entry in audit}
    assert {"knowledge.document_ingested", "knowledge.document_deleted"} <= actions


@pytest.mark.parametrize(
    ("name", "content", "doc_type", "code"),
    [
        ("p.exe", b"MZ\x90", "policy", 422),
        ("p.md", b"MZ\x90\x00", "policy", 422),
        ("p.md", b"", "policy", 422),
        ("p.md", b"\n\n", "policy", 422),
        ("p.pdf", b"not a pdf", "policy", 422),
        ("p.json", b"{broken", "questionnaire", 422),
        pytest.param("p.md", b"x" * 300_000, "policy", 413, id="too-large"),
    ],
)
def test_bad_uploads_are_rejected(
    kapp: FastAPI, org: Org, name: str, content: bytes, doc_type: str, code: int
) -> None:
    admin = client_for(kapp, org.users["admin"])
    assert upload(admin, content=content, name=name, doc_type=doc_type).status_code == code
    assert admin.get("/api/v1/knowledge/documents").json() == []


def test_viewer_and_system_owner_cannot_upload_or_delete(kapp: FastAPI, org: Org) -> None:
    admin = client_for(kapp, org.users["admin"])
    doc = upload(admin).json()
    for role in ("viewer", "system_owner"):
        c = client_for(kapp, org.users[role])
        assert upload(c).status_code == 403
        assert (
            c.delete(
                f"/api/v1/knowledge/documents/{doc['document_id']}", headers=csrf(c)
            ).status_code
            == 403
        )


def test_system_ingest_reads_the_evidence_and_is_idempotent(kapp: FastAPI, org: Org) -> None:
    admin = client_for(kapp, org.users["admin"])
    system_id = mk_system(admin, "Kiosk")
    uploaded = admin.post(
        f"/api/v1/systems/{system_id}/evidence",
        data={"kind": "privacy_policy"},
        files={"file": ("policy.md", POLICY, "text/markdown")},
        headers=csrf(admin),
    )
    assert uploaded.status_code == 201, uploaded.text
    admin.post(
        f"/api/v1/systems/{system_id}/evidence",
        data={"kind": "har"},
        files={"file": ("cap.har", b'{"log": {"entries": []}}', "application/json")},
        headers=csrf(admin),
    )

    ingested = admin.post(f"/api/v1/systems/{system_id}/knowledge/ingest", headers=csrf(admin))
    assert ingested.status_code == 200, ingested.text
    items = ingested.json()
    assert [i["status"] for i in items] == ["created"] and items[0][
        "title"
    ] == "Privacy notice: Kiosk"
    again = admin.post(f"/api/v1/systems/{system_id}/knowledge/ingest", headers=csrf(admin)).json()
    assert [i["status"] for i in again] == ["unchanged"]

    found = search(admin, "how long are orders kept", system_id=system_id, doc_types=["policy"])
    assert found["passages"][0]["metadata"]["heading"] == "How long we keep it"
    assert found["passages"][0]["metadata"]["system_id"] == system_id
    docs = admin.get("/api/v1/knowledge/documents", params={"system_id": system_id}).json()
    assert len(docs) == 1 and docs[0]["evidence_item_id"] == uploaded.json()["id"]


def test_system_owner_sees_own_systems_and_organisation_documents_only(
    kapp: FastAPI, org: Org
) -> None:
    admin = client_for(kapp, org.users["admin"])
    owner = client_for(kapp, org.users["system_owner"])
    mine = mk_system(admin, "Mine", org.users["system_owner"].id)
    theirs = mk_system(admin, "Theirs")
    note = b"## Scope\n\nQuokka telemetry is retained for ninety days."
    wide = upload(admin, content=note, name="wide.md").json()["document_id"]
    own = upload(admin, content=note, name="own.md", system_id=mine).json()["document_id"]
    other = upload(admin, content=note, name="other.md", system_id=theirs).json()["document_id"]

    seen = {
        p["metadata"]["document_id"]
        for p in search(owner, "quokka telemetry retained", sources=["document"], top_k=10)[
            "passages"
        ]
    }
    assert seen == {wide, own}
    assert {d["id"] for d in owner.get("/api/v1/knowledge/documents").json()} == {wide, own}
    assert (
        owner.post(
            "/api/v1/knowledge/search",
            json={"query": "quokka telemetry", "system_id": theirs},
            headers=csrf(owner),
        ).status_code
        == 404
    )
    assert (
        owner.get("/api/v1/knowledge/passage", params={"citation": f"doc:{other}#0"}).status_code
        == 404
    )
    assert (
        owner.get("/api/v1/knowledge/passage", params={"citation": f"doc:{own}#0"}).status_code
        == 200
    )
    everything = {
        p["metadata"]["document_id"]
        for p in search(admin, "quokka telemetry retained", sources=["document"], top_k=10)[
            "passages"
        ]
    }
    assert everything == {wide, own, other}


def test_rerank_flag_is_honoured_when_a_reranker_is_configured(
    settings: Settings,
    session_factory: sessionmaker[TenantSession],
    real_embedder: SentenceTransformerEmbedder,
    regulation_index: int,
    org: Org,
) -> None:
    from tests.fixtures_knowledge import CrossEncoderReranker  # noqa: F401  (skips if unavailable)

    app = create_app(
        settings.model_copy(update={"rerank_enabled": True, "rea_enabled": False}),
        session_factory,
        embedder=real_embedder,
    )
    c = client_for(app, org.users["viewer"])
    try:
        on = search(c, "records of processing activities", top_k=3)
    except AssertionError:
        pytest.skip("cross encoder not available offline")
    assert on["reranked"] is True and "rerank" in on["timings_ms"]
    assert on["passages"][0]["metadata"]["article"] == 30
    assert "rerank_score" in on["passages"][0]["signals"]
    off = search(c, "records of processing activities", top_k=3, rerank=False)
    assert off["reranked"] is False


def test_empty_knowledge_base_answers_503(settings: Settings, admin_url: Any, org: Org) -> None:
    from sqlalchemy import create_engine

    from alembic import command
    from app.classify.embedder import HashingEmbedder
    from app.db.session import make_engine, make_session_factory
    from app.services import provisioning
    from tests.conftest import alembic_config, app_url, create_database

    url = create_database(admin_url, "kb_empty")
    command.upgrade(alembic_config(url.render_as_string(hide_password=False)), "head")
    owner_engine = create_engine(url)
    empty_org_id = provisioning.create_organization(owner_engine, "Empty", "empty-org")
    user = provisioning.create_user(
        owner_engine, empty_org_id, "viewer@empty.example", "Viewer", "Correct-Horse-Battery-1",
        __import__("app.db.enums", fromlist=["Role"]).Role.VIEWER,
    )  # fmt: skip
    engine = make_engine(app_url(url).render_as_string(hide_password=False), pool_size=2)
    app = create_app(
        settings.model_copy(update={"rea_enabled": False}),
        make_session_factory(engine),
        embedder=HashingEmbedder(),
    )
    c = client_for(app, user)
    response = c.post(
        "/api/v1/knowledge/search", json={"query": "anything at all"}, headers=csrf(c)
    )
    assert response.status_code == 503
    engine.dispose()
    owner_engine.dispose()
