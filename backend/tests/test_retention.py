import base64
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.session import TenantSession
from app.services.evidence_store import EvidenceStore
from app.services.retention import purge_expired_evidence
from tests.fixtures_api import ENCRYPTION_KEY, Org, client_for, csrf

HAR = b'{"log": {"entries": []}}'


def _upload(c: TestClient, system_id: str) -> str:
    response = c.post(
        f"/api/v1/systems/{system_id}/evidence",
        data={"kind": "har"},
        files={"file": ("cap.har", HAR, "application/json")},
        headers=csrf(c),
    )
    return str(response.json()["id"])


def _backdate(engine: Engine, evidence_id: str, days: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE evidence_items SET created_at = now() - make_interval(days => :d) WHERE id = :i"
            ),
            {"d": days, "i": evidence_id},
        )


def test_expired_evidence_is_deleted_with_its_file(
    app: FastAPI,
    org: Org,
    other_org: Org,
    settings: Settings,
    owner_engine: Engine,
    session_factory: sessionmaker[TenantSession],
) -> None:
    c = client_for(app, org.users["admin"])
    sid = c.post("/api/v1/systems", json={"name": "Shop"}, headers=csrf(c)).json()["id"]
    old, recent = _upload(c, sid), _upload(c, sid)
    _backdate(owner_engine, old, 400)  # past the 365 day default
    _backdate(owner_engine, recent, 10)

    # A second organization with a shorter period, and a fresh file inside it.
    other = client_for(app, other_org.users["admin"])
    other.put("/api/v1/settings", json={"evidence_retention_days": 5}, headers=csrf(other))
    other_sid = other.post("/api/v1/systems", json={"name": "Blog"}, headers=csrf(other)).json()[
        "id"
    ]
    other_old, other_new = _upload(other, other_sid), _upload(other, other_sid)
    _backdate(owner_engine, other_old, 6)
    _backdate(owner_engine, other_new, 1)

    store = EvidenceStore(Path(settings.upload_dir), base64.b64decode(ENCRYPTION_KEY))
    before = len(list(Path(settings.upload_dir).rglob("*.enc")))
    assert before == 4

    purged = purge_expired_evidence(
        owner_engine, session_factory, store, settings.evidence_retention_days
    )
    assert purged[str(org.id)] == 1 and purged[str(other_org.id)] == 1

    remaining = {e["id"] for e in c.get(f"/api/v1/systems/{sid}/evidence").json()}
    assert remaining == {recent}
    assert {e["id"] for e in other.get(f"/api/v1/systems/{other_sid}/evidence").json()} == {
        other_new
    }
    names = {p.name for p in Path(settings.upload_dir).rglob("*.enc")}
    assert names == {f"{recent}.enc", f"{other_new}.enc"}

    entry = c.get("/api/v1/audit-log", params={"action": "evidence.retention_purge"}).json()[0]
    assert entry["details"] == {"deleted": 1, "retention_days": 365}

    # Idempotent: a second run finds nothing to delete.
    assert purge_expired_evidence(owner_engine, session_factory, store, 365) == {}


def test_purge_ignores_future_cutoff_boundary(
    app: FastAPI,
    org: Org,
    settings: Settings,
    owner_engine: Engine,
    session_factory: sessionmaker[TenantSession],
) -> None:
    c = client_for(app, org.users["admin"])
    sid = c.post("/api/v1/systems", json={"name": "Shop"}, headers=csrf(c)).json()["id"]
    evidence_id = _upload(c, sid)
    store = EvidenceStore(Path(settings.upload_dir), base64.b64decode(ENCRYPTION_KEY))
    now = datetime.now(UTC)
    assert purge_expired_evidence(owner_engine, session_factory, store, 30, now=now) == {}
    later = now + timedelta(days=31)
    result = purge_expired_evidence(owner_engine, session_factory, store, 30, now=later)
    assert org.id.hex and result.get(str(org.id)) == 1
    assert c.get(f"/api/v1/systems/{sid}/evidence").json() == []
    assert evidence_id not in {p.stem for p in Path(settings.upload_dir).rglob("*.enc")}
