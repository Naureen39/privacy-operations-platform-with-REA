"""Classification through the API and the database: stored decisions, review queue, vendors."""

import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.classify.embedder import HashingEmbedder, SentenceTransformerEmbedder
from app.classify.features import ElementFeatures
from app.classify.index import MemoryMatcher, PgMatcher, load_index
from app.classify.knowledge import default_knowledge
from app.core.config import Settings
from app.db.models import TaxonomyEntry
from app.db.session import TenantSession, make_engine, make_session_factory
from app.main import create_app
from app.services import provisioning
from tests.conftest import APP_PASSWORD, alembic_config, app_url, create_database
from tests.discovery_scoring import ground_truth, location_key
from tests.fixtures_api import PASSWORD, Org, client_for, csrf, login
from tests.test_discovery_api import create_system, get_json, run_discovery, upload_estate_system

KNOWLEDGE = default_knowledge()


@pytest.fixture
def csettings(settings: Settings, tmp_path: Path) -> Settings:
    return settings.model_copy(
        update={
            "rea_enabled": False,
            "rea_input_dir": str(tmp_path / "stage"),
            "max_upload_bytes": 400_000,
            "embedding_local_files_only": True,
        }
    )


@pytest.fixture
def capp(
    csettings: Settings,
    session_factory: sessionmaker[TenantSession],
    real_embedder: SentenceTransformerEmbedder,
    taxonomy_index: int,
) -> FastAPI:
    return create_app(csettings, session_factory, embedder=real_embedder)


def discover_and_classify(
    client: TestClient, estate_id: str, name: str | None = None
) -> tuple[str, dict[str, Any]]:
    system_id = create_system(client, name or estate_id)
    upload_estate_system(client, system_id, estate_id)
    run_discovery(client, system_id)
    response = client.post(f"/api/v1/systems/{system_id}/classification", headers=csrf(client))
    assert response.status_code == 200, response.text
    return system_id, dict(response.json())


def elements_of(client: TestClient, system_id: str) -> list[dict[str, Any]]:
    return list(get_json(client, f"/api/v1/systems/{system_id}/data-elements?limit=1000"))


def key_of(item: dict[str, Any]) -> tuple[str, ...]:
    ctx = item["context"]
    if ctx["location_kind"] == "db_column":
        return ("db_column", ctx["table"], item["name"])
    return (ctx["location_kind"], item["name"])


def findings(engine: Engine, system_id: str) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT type, severity, status, dedupe_key, title FROM findings WHERE system_id = :s ORDER BY dedupe_key"
            ),
            {"s": system_id},
        ).mappings()
        return [dict(r) for r in rows]


# --- the main path -------------------------------------------------------------------------------
def test_classification_stores_decisions_vendors_and_review_items(
    capp: FastAPI, org: Org, owner_engine: Engine
) -> None:
    admin = client_for(capp, org.users["admin"])
    system_id, summary = discover_and_classify(admin, "clinic_portal")

    assert summary["elements"] > 20 and summary["classified"] >= summary["elements"] * 0.5
    assert (
        summary["special_strong"] >= 5
        and summary["recipients"] == 2
        and summary["recipients_unknown"] == 0
    )
    assert summary["thresholds_version"] and summary["embedding_model"] == "BAAI/bge-small-en-v1.5"
    assert get_json(admin, f"/api/v1/systems/{system_id}")["status"] == "CLASSIFIED"

    items = elements_of(admin, system_id)
    labels = {
        location_key(loc): (e["category"], e["special_category"])
        for e in ground_truth("clinic_portal")["data_elements"]
        for loc in e["locations"]
    }
    labelled = [(i, labels[key_of(i)]) for i in items if key_of(i) in labels]
    assert sum(i["category"] == want[0] for i, want in labelled) / len(labelled) >= 0.9
    for item, (_, special) in labelled:
        if special:  # health data is flagged, either as special category or escalated as near one
            assert item["special_category"] or item["context"]["classification"]["special"], item[
                "name"
            ]

    # Each decision keeps its reasons, confidence and the thresholds it was made with.
    classified = [i for i in items if i["category"]]
    assert all(0 < float(i["confidence"]) <= 1 for i in classified)
    assert all(
        i["context"]["classification"]["thresholds_version"] == summary["thresholds_version"]
        for i in items
    )
    assert all(i["context"]["classification"]["reasons"] for i in classified)
    assert all(i["context"]["classification"]["description"] for i in items)
    diagnosis = next(i for i in items if i["name"] == "diagnosis")
    assert (
        diagnosis["category"] == "health_data"
        and diagnosis["special_category"]
        and diagnosis["special_category_label"]
    )

    with owner_engine.connect() as conn:  # embeddings are stored with the elements
        missing = conn.execute(
            text("SELECT count(*) FROM data_elements WHERE system_id = :s AND embedding IS NULL"),
            {"s": system_id},
        ).scalar_one()
        assert missing == 0

    recipients = {
        r["domain"]: r for r in get_json(admin, f"/api/v1/systems/{system_id}/recipients")
    }
    assert (
        recipients["api.smsgate.example"]["vendor"] == "SMSGate"
        and recipients["api.smsgate.example"]["country"] == "IN"
    )
    assert (
        recipients["cal.bookwell.example"]["role"] == "processor"
        and recipients["cal.bookwell.example"]["category"] == "booking"
    )

    rows = findings(owner_engine, system_id)
    special_findings = [f for f in rows if f["type"] == "special_category_review"]
    flagged = [i for i in items if i["context"]["classification"]["special"]]
    assert len(special_findings) == len(flagged) >= 5
    assert {f["severity"] for f in special_findings} <= {"high", "medium"} and all(
        f["status"] == "open" for f in special_findings
    )
    assert len({f["dedupe_key"] for f in rows}) == len(rows)


def test_hr_and_newsletter_special_and_plain_systems(capp: FastAPI, org: Org) -> None:
    admin = client_for(capp, org.users["admin"])
    hr_id, hr = discover_and_classify(admin, "hr_onboarding")
    items = {
        i["name"]: i
        for i in elements_of(admin, hr_id)
        if i["context"]["location_kind"] == "db_column"
    }
    for name, expected in (
        ("disability_status", "health_data"),
        ("union_member", "trade_union_membership"),
        ("ethnic_origin", "racial_ethnic_origin"),
    ):
        assert items[name]["category"] == expected and items[name]["special_category"], name
    assert items["iban"]["category"] == "bank_account" and not items["iban"]["special_category"]
    assert hr["special_strong"] >= 3

    news_id, news = discover_and_classify(admin, "newsletter")
    assert (
        news["special_strong"] == 0 and news["recipients_unknown"] == 0
    )  # nothing special, nothing unknown
    assert any(i["category"] == "consent_record" for i in elements_of(admin, news_id))


def test_rerun_is_idempotent_and_keeps_reviewed_decisions(
    capp: FastAPI, org: Org, owner_engine: Engine
) -> None:
    admin = client_for(capp, org.users["admin"])
    system_id, first = discover_and_classify(admin, "crm")
    before = findings(owner_engine, system_id)
    target = next(
        i
        for i in elements_of(admin, system_id)
        if i["name"] == "title" and i["context"]["location_kind"] == "db_column"
    )

    reviewed = admin.patch(
        f"/api/v1/systems/{system_id}/data-elements/{target['id']}",
        json={"review_status": "overridden", "category": "employment_data"},
        headers=csrf(admin),
    )
    assert reviewed.status_code == 200 and reviewed.json()["category"] == "employment_data"
    assert (
        reviewed.json()["review_status"] == "overridden"
        and float(reviewed.json()["confidence"]) == 1.0
    )

    second = admin.post(f"/api/v1/systems/{system_id}/classification", headers=csrf(admin)).json()
    assert second["reviewed_kept"] == 1 and second["elements"] == first["elements"]
    after = elements_of(admin, system_id)
    kept = next(i for i in after if i["id"] == target["id"])
    assert kept["category"] == "employment_data" and kept["review_status"] == "overridden"
    assert (
        len(findings(owner_engine, system_id)) <= len(before) + 0
    )  # no duplicates on a second run
    assert len({f["dedupe_key"] for f in findings(owner_engine, system_id)}) == len(
        findings(owner_engine, system_id)
    )


def test_review_endpoint_validation_roles_and_audit(
    capp: FastAPI, org: Org, other_org: Org
) -> None:
    admin = client_for(capp, org.users["admin"])
    system_id, _ = discover_and_classify(admin, "newsletter")
    email = next(
        i
        for i in elements_of(admin, system_id)
        if i["name"] == "email" and i["context"]["location_kind"] == "form_field"
    )
    url = f"/api/v1/systems/{system_id}/data-elements/{email['id']}"

    assert (
        admin.patch(
            url,
            json={"review_status": "overridden", "category": "no_such_category"},
            headers=csrf(admin),
        ).status_code
        == 422
    )
    assert admin.patch(url, json={"review_status": "bogus"}, headers=csrf(admin)).status_code == 422
    assert (
        admin.patch(
            f"/api/v1/systems/{system_id}/data-elements/{uuid.uuid4()}",
            json={"review_status": "accepted"},
            headers=csrf(admin),
        ).status_code
        == 404
    )
    accepted = admin.patch(url, json={"review_status": "accepted"}, headers=csrf(admin)).json()
    assert accepted["review_status"] == "accepted" and accepted["category"] == email["category"]
    not_personal = admin.patch(
        url, json={"review_status": "overridden", "not_personal_data": True}, headers=csrf(admin)
    ).json()
    assert not_personal["category"] is None and not not_personal["special_category"]
    special = admin.patch(
        url, json={"review_status": "overridden", "category": "health_data"}, headers=csrf(admin)
    ).json()
    assert special["special_category"] is True and special["special_category_label"]

    viewer = client_for(capp, org.users["viewer"])
    owner = client_for(capp, org.users["system_owner"])
    outsider = client_for(capp, other_org.users["admin"])
    for denied in (viewer, owner):
        assert (
            denied.patch(url, json={"review_status": "accepted"}, headers=csrf(denied)).status_code
            == 403
        )
        assert (
            denied.post(
                f"/api/v1/systems/{system_id}/classification", headers=csrf(denied)
            ).status_code
            == 403
        )
    assert (
        outsider.patch(url, json={"review_status": "accepted"}, headers=csrf(outsider)).status_code
        == 404
    )
    assert (
        outsider.post(
            f"/api/v1/systems/{system_id}/classification", headers=csrf(outsider)
        ).status_code
        == 404
    )

    actions = {e["action"] for e in get_json(admin, "/api/v1/audit-log?limit=500")}
    assert {"classification.run", "classification.review"} <= actions
    entry = next(
        e
        for e in get_json(admin, "/api/v1/audit-log?action=classification.run")
        if e["entity_id"] == system_id
    )
    assert entry["details"]["thresholds_version"] and "classified" in entry["details"]


def test_unknown_recipient_hosts_become_review_items(
    capp: FastAPI, org: Org, owner_engine: Engine
) -> None:
    admin = client_for(capp, org.users["admin"])
    system_id, _ = discover_and_classify(admin, "newsletter")
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO recipients (org_id, system_id, domain, context, evidence_id) "
                "SELECT org_id, id, 'tracker.mystery-vendor.test', '{}'::jsonb, "
                "(SELECT evidence_id FROM data_elements WHERE system_id = :s LIMIT 1) FROM systems WHERE id = :s"
            ),
            {"s": system_id},
        )
    summary = admin.post(f"/api/v1/systems/{system_id}/classification", headers=csrf(admin)).json()
    assert summary["recipients_unknown"] == 1 and summary["findings_open"] >= 1
    unknown = [
        f for f in findings(owner_engine, system_id) if f["type"] == "unknown_recipient_host"
    ]
    assert (
        len(unknown) == 1
        and unknown[0]["status"] == "open"
        and "mystery-vendor" in unknown[0]["title"]
    )

    admin.post(f"/api/v1/systems/{system_id}/classification", headers=csrf(admin))
    assert (
        len([f for f in findings(owner_engine, system_id) if f["type"] == "unknown_recipient_host"])
        == 1
    )  # not duplicated

    with owner_engine.begin() as conn:  # a person identifies the vendor: the review item closes
        conn.execute(
            text(
                "UPDATE recipients SET vendor = 'Mystery Vendor' WHERE system_id = :s AND domain = 'tracker.mystery-vendor.test'"
            ),
            {"s": system_id},
        )
    admin.post(f"/api/v1/systems/{system_id}/classification", headers=csrf(admin))
    assert [
        f["status"]
        for f in findings(owner_engine, system_id)
        if f["type"] == "unknown_recipient_host"
    ] == ["resolved"]
    recipients = {
        r["domain"]: r for r in get_json(admin, f"/api/v1/systems/{system_id}/recipients")
    }
    assert (
        recipients["tracker.mystery-vendor.test"]["vendor"] == "Mystery Vendor"
    )  # a person's entry is kept


def test_taxonomy_endpoint_lists_the_categories(capp: FastAPI, org: Org) -> None:
    for role in ("viewer", "system_owner", "analyst", "admin"):
        categories = get_json(client_for(capp, org.users[role]), "/api/v1/taxonomy")
        assert len(categories) == len(KNOWLEDGE.categories)
    special = {c["id"] for c in categories if c["special_category"]}
    assert special == set(KNOWLEDGE.special)


def test_classification_does_not_leak_across_organizations(
    capp: FastAPI, org: Org, other_org: Org
) -> None:
    admin = client_for(capp, org.users["admin"])
    system_id, _ = discover_and_classify(admin, "crm")
    outsider = client_for(capp, other_org.users["admin"])
    assert outsider.get(f"/api/v1/systems/{system_id}/data-elements").status_code == 404
    other_system = create_system(outsider, "Other")
    assert elements_of(outsider, other_system) == []


# --- the index in PostgreSQL ---------------------------------------------------------------------
def test_pgvector_lookup_agrees_with_the_in_memory_lookup(
    real_embedder: SentenceTransformerEmbedder, taxonomy_index: int, app_engine: Engine
) -> None:
    descriptions = [
        ElementFeatures(name=n, location_kind="request_json_key").description()
        for n in (
            "billing_email",
            "telephone",
            "date_of_birth",
            "diagnosis",
            "latitude",
            "order_total",
            "password",
            "religion",
        )
    ]
    vectors = real_embedder.embed(descriptions)
    memory = MemoryMatcher(KNOWLEDGE, real_embedder).top(vectors)
    with Session(app_engine) as session:
        assert session.scalar(select(TaxonomyEntry.id).limit(1)) is not None
        stored = PgMatcher(session).top(vectors)
    assert taxonomy_index > 300
    for a, b in zip(memory, stored, strict=True):
        assert a[0].category_id == b[0].category_id
        assert abs(a[0].similarity - b[0].similarity) < 1e-3
        assert all(
            abs(x.similarity - y.similarity) < 1e-3 for x, y in zip(a[:5], b[:5], strict=True)
        )


class CountingEmbedder(HashingEmbedder):
    name = "counting"

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return super().embed(texts)


def test_loading_the_index_is_idempotent_and_versioned(admin_url: URL) -> None:
    url = create_database(admin_url, "taxonomy_load")
    command.upgrade(alembic_config(url.render_as_string(hide_password=False)), "head")
    engine = create_engine(url)
    embedder = CountingEmbedder()
    try:
        first = load_index(engine, KNOWLEDGE, embedder)
        assert first > 300 and embedder.calls == 1
        assert (
            load_index(engine, KNOWLEDGE, embedder) == first and embedder.calls == 1
        )  # unchanged: no work
        assert load_index(engine, KNOWLEDGE, embedder, force=True) == first and embedder.calls == 2
        other = HashingEmbedder()
        other.name = "another-model"
        load_index(engine, KNOWLEDGE, other)  # a different model reloads the entries
        with engine.connect() as conn:
            versions = (
                conn.execute(text("SELECT DISTINCT source_version FROM taxonomy_entries"))
                .scalars()
                .all()
            )
        assert len(versions) == 1 and "another-model" in versions[0]
    finally:
        engine.dispose()


def test_classification_reports_a_missing_index(admin_url: URL, csettings: Settings) -> None:
    url = create_database(admin_url, "no_index")
    command.upgrade(alembic_config(url.render_as_string(hide_password=False)), "head")
    owner = create_engine(url)
    try:
        org_id = provisioning.create_organization(owner, "NoIndex", "noindex")
        user = provisioning.create_user(
            owner,
            org_id,
            "admin@noindex.example",
            "Admin",
            PASSWORD,
            __import__("app.db.enums", fromlist=["Role"]).Role.ADMIN,
        )
        engine = make_engine(app_url(url).render_as_string(hide_password=False), pool_size=2)
        app = create_app(csettings, make_session_factory(engine), embedder=HashingEmbedder())
        with TestClient(app, base_url="https://testserver") as client:
            assert login(client, user.email).status_code == 200
            system_id = create_system(client, "Empty")
            response = client.post(
                f"/api/v1/systems/{system_id}/classification", headers=csrf(client)
            )
            assert response.status_code == 503 and "taxonomy index" in response.json()["detail"]
        engine.dispose()
    finally:
        owner.dispose()
    _ = (APP_PASSWORD, Callable, json)
