import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.core.config import Settings
from app.services.evidence_store import EvidenceStore
from tests.fixtures_api import ENCRYPTION_KEY, Org, client_for, csrf

HAR = json.dumps(
    {"log": {"entries": [{"request": {"url": "https://shop.example.test/"}}]}}
).encode()


@pytest.fixture
def admin(app: FastAPI, org: Org) -> TestClient:
    return client_for(app, org.users["admin"])


@pytest.fixture
def system_id(admin: TestClient) -> str:
    response = admin.post("/api/v1/systems", json={"name": "Web shop"}, headers=csrf(admin))
    return str(response.json()["id"])


def upload(c: TestClient, system_id: str, name: str, content: bytes, kind: str = "har") -> Any:
    return c.post(
        f"/api/v1/systems/{system_id}/evidence",
        data={"kind": kind},
        files={"file": (name, content, "application/octet-stream")},
        headers=csrf(c),
    )


def test_upload_is_stored_encrypted_with_matching_checksum(
    admin: TestClient, system_id: str, settings: Settings, org: Org
) -> None:
    response = upload(admin, system_id, "capture.har", HAR)
    assert response.status_code == 201
    item = response.json()
    assert item["checksum_sha256"] == hashlib.sha256(HAR).hexdigest()
    assert item["encrypted"] is True and item["size_bytes"] == len(HAR)
    assert "storage_path" not in item  # internal detail is not exposed

    files = list(Path(settings.upload_dir).rglob("*.enc"))
    assert len(files) == 1
    raw = files[0].read_bytes()
    assert b"shop.example.test" not in raw and b"entries" not in raw
    assert str(org.id) in files[0].as_posix() and item["id"] in files[0].name

    import base64
    import uuid

    store = EvidenceStore(Path(settings.upload_dir), base64.b64decode(ENCRYPTION_KEY))
    relative = files[0].relative_to(Path(settings.upload_dir).resolve()).as_posix()
    assert store.read(relative, uuid.UUID(item["id"])) == HAR
    assert admin.get(f"/api/v1/systems/{system_id}/evidence").json()[0]["id"] == item["id"]


@pytest.mark.parametrize(
    ("name", "content", "kind", "code"),
    [
        ("capture.exe", HAR, "har", 422),
        ("capture.har", b"MZ\x90\x00" + b"\x00" * 100, "har", 422),
        ("capture.har", b"\x7fELF" + b"\x00" * 100, "har", 422),
        ("capture.har", b"{not json", "har", 422),
        ("capture.sqlite", b"plain text", "sqlite_snapshot", 422),
        ("capture.har", b"", "har", 422),
        ("capture.har", HAR, "not_a_kind", 422),
    ],
)
def test_bad_uploads_are_rejected_and_nothing_is_stored(
    admin: TestClient,
    system_id: str,
    settings: Settings,
    name: str,
    content: bytes,
    kind: str,
    code: int,
) -> None:
    assert upload(admin, system_id, name, content, kind).status_code == code
    assert not list(Path(settings.upload_dir).rglob("*"))
    assert admin.get(f"/api/v1/systems/{system_id}/evidence").json() == []


def test_oversized_upload_is_refused(admin: TestClient, system_id: str, settings: Settings) -> None:
    too_big = b"{" + b" " * (settings.max_upload_bytes + 10) + b"}"
    assert upload(admin, system_id, "capture.har", too_big).status_code == 413
    assert not list(Path(settings.upload_dir).rglob("*"))


def test_rejected_upload_is_audited(admin: TestClient, system_id: str) -> None:
    upload(admin, system_id, "capture.exe", HAR)
    entries = admin.get("/api/v1/audit-log", params={"action": "evidence.upload_rejected"}).json()
    assert len(entries) == 1 and "Extension" in entries[0]["details"]["reason"]


def test_traversal_in_filename_cannot_escape_storage(
    admin: TestClient, system_id: str, settings: Settings, tmp_path: Path
) -> None:
    response = upload(admin, system_id, "../../../outside.har", HAR)
    assert response.status_code == 201
    assert response.json()["filename"] == "outside.har"
    assert not (tmp_path / "outside.har").exists()
    stored = list(Path(settings.upload_dir).rglob("*.enc"))
    assert len(stored) == 1 and stored[0].resolve().is_relative_to(
        Path(settings.upload_dir).resolve()
    )


def test_evidence_store_refuses_paths_outside_its_directory(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "evidence", b"k" * 32)
    with pytest.raises(ValueError):
        store.read("../secret.enc", __import__("uuid").uuid4())
    with pytest.raises(ValueError):
        store.delete("../../secret.enc")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",  # loopback
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata, link local
        "http://10.0.0.5/admin",  # private range outside the demo network
        "https://evil.example/",  # not on the allowlist
        "http://localhost/",  # not on the allowlist
        "file:///etc/passwd",
        "https://user:pw@93.184.216.34/",
        "https://93.184.216.34:8080/",
    ],
)
def test_forged_observation_urls_are_refused(admin: TestClient, system_id: str, url: str) -> None:
    response = admin.post(
        f"/api/v1/systems/{system_id}/evidence/url",
        json={"url": url},
        headers=csrf(admin),
    )
    assert response.status_code == 422
    assert admin.get(f"/api/v1/systems/{system_id}/evidence").json() == []


def test_allowlisted_public_url_is_registered(admin: TestClient, system_id: str) -> None:
    response = admin.post(
        f"/api/v1/systems/{system_id}/evidence/url",
        json={"url": "https://93.184.216.34/"},
        headers=csrf(admin),
    )
    assert response.status_code == 201
    assert response.json()["kind"] == "website" and response.json()["encrypted"] is False


def test_demo_network_is_allowed_when_configured(
    make_app: Any, settings: Settings, org: Org
) -> None:
    configured = settings.model_copy(update={"observation_allowed_networks": ["10.0.0.0/24"]})
    c = client_for(make_app(configured), org.users["admin"])
    sid = c.post("/api/v1/systems", json={"name": "Internal"}, headers=csrf(c)).json()["id"]
    inside = c.post(
        f"/api/v1/systems/{sid}/evidence/url",
        json={"url": "http://10.0.0.5/"},
        headers=csrf(c),
    )
    assert inside.status_code == 201
    still_blocked = c.post(
        f"/api/v1/systems/{sid}/evidence/url",
        json={"url": "http://127.0.0.1/"},
        headers=csrf(c),
    )
    assert still_blocked.status_code == 422


def test_settings_roundtrip_and_validation(admin: TestClient) -> None:
    defaults = admin.get("/api/v1/settings").json()
    assert defaults["llm_provider_order"] == ["groq", "gemini"]
    assert defaults["evidence_retention_days"] == 365

    updated = {
        **defaults,
        "llm_provider_order": ["gemini", "groq"],
        "evidence_retention_days": 90,
    }
    assert admin.put("/api/v1/settings", json=updated, headers=csrf(admin)).status_code == 200
    assert admin.get("/api/v1/settings").json() == updated

    for bad in (
        {"llm_provider_order": ["openai"]},
        {"llm_provider_order": ["groq", "groq"]},
        {"llm_provider_order": []},
        {"daily_token_budget_org": 5},
        {"evidence_retention_days": 0},
    ):
        assert admin.put("/api/v1/settings", json=bad, headers=csrf(admin)).status_code == 422

    entry = admin.get("/api/v1/audit-log", params={"action": "settings.update"}).json()[0]
    assert entry["details"] == {"changed": ["evidence_retention_days", "llm_provider_order"]}


def test_settings_are_per_organization(app: FastAPI, admin: TestClient, other_org: Org) -> None:
    admin.put("/api/v1/settings", json={"evidence_retention_days": 7}, headers=csrf(admin))
    other = client_for(app, other_org.users["admin"])
    assert other.get("/api/v1/settings").json()["evidence_retention_days"] == 365


def test_secrets_are_validated_at_startup(session_factory: Any, settings: Settings) -> None:
    from app.core.config import ConfigurationError
    from app.main import create_app

    for update in (
        {"jwt_secret": None},
        {"jwt_secret": "short"},
        {"evidence_encryption_key": None},
        {"evidence_encryption_key": "not base64!!"},
        {"evidence_encryption_key": "c2hvcnQ="},
    ):
        with pytest.raises(ConfigurationError):
            create_app(Settings(**{**settings.model_dump(), **update}), session_factory)


def test_database_has_no_plaintext_secrets(
    admin: TestClient, org: Org, owner_engine: Engine
) -> None:
    with owner_engine.connect() as conn:
        hashes = conn.execute(
            text(
                "SELECT password_hash FROM users u JOIN memberships m ON m.user_id = u.id WHERE m.org_id = :o"
            ),
            {"o": org.id},
        ).all()
        tokens = conn.execute(text("SELECT token_hash FROM refresh_tokens")).all()
    assert hashes and all(h[0].startswith("$argon2id$") for h in hashes)
    refresh = admin.cookies.get("pl_refresh", path="/api/v1/auth")
    assert refresh and all(refresh != t[0] for t in tokens)
    assert all(len(t[0]) == 64 for t in tokens)
