"""Discovery through the API: runs, stored facts, provenance, masking, permissions."""

import csv
import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.core.config import Settings
from tests.discovery_scoring import ESTATE, aggregate, score_system
from tests.fixtures_api import Org, client_for, csrf
from tests.rea_support import rea_unavailable_reason

KIND_FILES = [
    ("har", "capture.har"),
    ("website", "website_snapshot.html"),
    ("javascript_bundle", None),
    ("sqlite_snapshot", "snapshot.sqlite"),
]


@pytest.fixture
def dsettings(settings: Settings, tmp_path: Path) -> Settings:
    return settings.model_copy(
        update={
            "rea_input_dir": str(tmp_path / "rea_input"),
            "rea_observation_ms": 1000,
            "max_upload_bytes": 400_000,
            "rea_enabled": rea_unavailable_reason() is None,
        }
    )


@pytest.fixture
def fallback_settings(dsettings: Settings) -> Settings:
    return dsettings.model_copy(update={"rea_enabled": False})


def create_system(client: TestClient, name: str = "Web shop", owner: object = None) -> str:
    body: dict[str, Any] = {"name": name}
    if owner:
        body["owner_user_id"] = str(owner)
    response = client.post("/api/v1/systems", json=body, headers=csrf(client))
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def upload_estate_system(client: TestClient, system_id: str, estate_id: str) -> list[str]:
    ids = []
    for kind, name in KIND_FILES:
        filename = name or ("main.bundle.js" if estate_id == "staff_desktop" else "app.bundle.js")
        content = (ESTATE / estate_id / "evidence" / filename).read_bytes()
        response = client.post(
            f"/api/v1/systems/{system_id}/evidence",
            data={"kind": kind},
            files={"file": (filename, content, "application/octet-stream")},
            headers=csrf(client),
        )
        assert response.status_code == 201, (kind, response.text)
        ids.append(str(response.json()["id"]))
    return ids


def run_discovery(client: TestClient, system_id: str) -> dict[str, Any]:
    response = client.post(f"/api/v1/systems/{system_id}/discovery-runs", headers=csrf(client))
    assert response.status_code == 201, response.text
    return dict(response.json())


def get_json(client: TestClient, path: str) -> Any:
    response = client.get(path)
    assert response.status_code == 200, response.text
    return response.json()


def as_candidates(items: list[dict[str, Any]]) -> list[Any]:
    return [
        SimpleNamespace(
            name=i["name"], location_kind=i["context"]["location_kind"], context=i["context"]
        )
        for i in items
    ]


def evidence_rows(engine: Engine, run_id: str) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id::text AS id, extractor, command, rea_version, duration_ms, status, error, raw_sha256, "
                "raw_truncated, raw_output::text AS raw FROM discovery_evidence WHERE run_id = :r ORDER BY created_at"
            ),
            {"r": run_id},
        ).mappings()
        return [dict(r) for r in rows]


# --- the main path -----------------------------------------------------------------------------
@pytest.mark.skipif(rea_unavailable_reason() is not None, reason=rea_unavailable_reason() or "")
def test_discovery_with_rea_stores_linked_facts_and_meets_acceptance(
    app_factory: Callable[[Settings], FastAPI], dsettings: Settings, org: Org, owner_engine: Engine
) -> None:
    admin = client_for(app_factory(dsettings), org.users["admin"])
    scores = []
    for estate_id in ("web_shop", "staff_desktop"):
        system_id = create_system(admin, estate_id)
        upload_estate_system(admin, system_id, estate_id)
        run = run_discovery(admin, system_id)
        assert run["state"] == "DISCOVERING" and run["error"] is None
        assert (
            run["summary"]["status"] == "completed" and run["summary"]["extractor_mix"]["rea"] >= 4
        )

        elements = get_json(admin, f"/api/v1/systems/{system_id}/data-elements?limit=1000")
        recipients = get_json(admin, f"/api/v1/systems/{system_id}/recipients")
        technologies = get_json(admin, f"/api/v1/systems/{system_id}/technologies")
        scores.append(
            score_system(estate_id, as_candidates(elements), {r["domain"] for r in recipients})
        )
        assert technologies and recipients and elements

        # Every fact points at the raw output of the extractor run that produced it.
        rows = {r["id"]: r for r in evidence_rows(owner_engine, run["id"])}
        for fact in (*elements, *recipients, *technologies):
            assert fact["evidence_id"] in rows, fact["name" if "name" in fact else "domain"]
            row = rows[fact["evidence_id"]]
            assert (
                row["status"] == "ok"
                and row["command"]
                and row["duration_ms"] is not None
                and row["raw_sha256"]
            )
            if row["extractor"] == "rea":
                assert row["rea_version"] == "6.7.0" and row["command"].startswith("rea ")
            for supporting in fact["context"].get("discovery_evidence_ids", []):
                assert supporting in rows

        by_source = {e["source_kind"] for e in elements}
        # The desktop client's page has no form, so only the web shop yields input fields.
        assert by_source == (
            {"har", "website", "sqlite_snapshot"}
            if estate_id == "web_shop"
            else {"har", "sqlite_snapshot"}
        )
        form = [e for e in elements if e["source_kind"] == "website"]
        assert all(
            rows[e["evidence_id"]]["extractor"] == "fallback" for e in form
        )  # REA hides input names
        db_cols = [e for e in elements if e["source_kind"] == "sqlite_snapshot"]
        assert all(rows[e["evidence_id"]]["extractor"] == "rea" for e in db_cols)

        detail = get_json(admin, f"/api/v1/discovery-evidence/{elements[0]['evidence_id']}")
        assert detail["status"] == "ok" and detail["raw_output"]

    total = aggregate(scores)
    assert total.element_recall >= 0.9 and total.host_recall >= 0.95, (
        total.missed_elements,
        total.missed_hosts,
    )


def test_raw_output_is_stored_without_sample_values(
    app_factory: Callable[[Settings], FastAPI],
    fallback_settings: Settings,
    org: Org,
    owner_engine: Engine,
) -> None:
    admin = client_for(app_factory(fallback_settings), org.users["admin"])
    system_id = create_system(admin)
    upload_estate_system(admin, system_id, "web_shop")
    run = run_discovery(admin, system_id)
    rows = evidence_rows(owner_engine, run["id"])
    assert len(rows) == 4 and {r["extractor"] for r in rows} == {"fallback"}
    with (ESTATE.parent / "people" / "synthetic_people.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        people = list(csv.DictReader(handle))
    blob = "\n".join(r["raw"] or "" for r in rows)
    facts = json.dumps(
        get_json(admin, f"/api/v1/systems/{system_id}/data-elements?limit=1000")
    ) + json.dumps(get_json(admin, f"/api/v1/systems/{system_id}/recipients"))
    for person in people:
        for value in (person["email"], person["phone"], person["iban"], person["national_id"]):
            assert value not in blob and value not in facts, value
    assert "4242424242424242" not in blob  # the test card number sent to the payment provider
    assert all(len(r["raw_sha256"]) == 64 for r in rows)


def test_rerun_is_idempotent_and_keeps_reviewed_elements(
    app_factory: Callable[[Settings], FastAPI],
    fallback_settings: Settings,
    org: Org,
    owner_engine: Engine,
) -> None:
    admin = client_for(app_factory(fallback_settings), org.users["admin"])
    system_id = create_system(admin)
    upload_estate_system(admin, system_id, "web_shop")
    first = run_discovery(admin, system_id)
    counts = [
        len(
            get_json(
                admin,
                (
                    f"/api/v1/systems/{system_id}/{p}?limit=1000"
                    if p == "data-elements"
                    else f"/api/v1/systems/{system_id}/{p}"
                ),
            )
        )
        for p in ("data-elements", "recipients", "technologies")
    ]

    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE data_elements SET review_status = 'accepted', category = 'contact_email' WHERE system_id = :s AND name = 'billing_email'"
            ),
            {"s": system_id},
        )
        conn.execute(
            text(
                "UPDATE recipients SET vendor = 'Stripe' WHERE system_id = :s AND domain = 'api.stripe.com'"
            ),
            {"s": system_id},
        )
    second = run_discovery(admin, system_id)
    again = [
        len(
            get_json(
                admin,
                (
                    f"/api/v1/systems/{system_id}/{p}?limit=1000"
                    if p == "data-elements"
                    else f"/api/v1/systems/{system_id}/{p}"
                ),
            )
        )
        for p in ("data-elements", "recipients", "technologies")
    ]
    assert again == counts and first["id"] != second["id"]
    assert len(get_json(admin, f"/api/v1/systems/{system_id}/discovery-runs")) == 2

    elements = get_json(admin, f"/api/v1/systems/{system_id}/data-elements?limit=1000")
    reviewed = [
        e for e in elements if e["name"] == "billing_email" and e["review_status"] == "accepted"
    ]
    assert reviewed and all(e["category"] == "contact_email" for e in reviewed)
    stripe = next(
        r
        for r in get_json(admin, f"/api/v1/systems/{system_id}/recipients")
        if r["domain"] == "api.stripe.com"
    )
    assert stripe["vendor"] == "Stripe"
    # Facts now point at the newest run, never at a deleted row.
    newest = {r["id"] for r in evidence_rows(owner_engine, second["id"])}
    assert all(e["evidence_id"] in newest for e in elements)
    system = get_json(admin, f"/api/v1/systems/{system_id}")
    assert system["status"] == "DISCOVERING" and system["last_discovery_at"]


def test_failed_rea_calls_are_recorded_and_the_fallback_takes_over(
    app_factory: Callable[[Settings], FastAPI], dsettings: Settings, org: Org, owner_engine: Engine
) -> None:
    broken_runner = (
        "const h=process.argv.includes('health');"
        "process.stdout.write(JSON.stringify(h?{ok:true,commands:[]}:{ok:false,error:{code:'rea_error',message:'simulated failure'}}))"
    )
    settings = dsettings.model_copy(
        update={"rea_enabled": True, "rea_local_command": ["node", "-e", broken_runner]}
    )
    admin = client_for(app_factory(settings), org.users["admin"])
    system_id = create_system(admin)
    upload_estate_system(admin, system_id, "newsletter")
    run = run_discovery(admin, system_id)
    assert run["state"] == "DISCOVERING"
    rows = evidence_rows(owner_engine, run["id"])
    failed = [r for r in rows if r["extractor"] == "rea"]
    assert len(failed) == 4 and all(
        r["status"] == "error" and "simulated failure" in r["error"] for r in failed
    )
    assert all(r["rea_version"] is None and r["raw"] is None for r in failed)
    ok_rows = [r for r in rows if r["status"] == "ok"]
    assert {r["extractor"] for r in ok_rows} == {"fallback"}
    elements = get_json(admin, f"/api/v1/systems/{system_id}/data-elements?limit=1000")
    ok_ids = {r["id"] for r in ok_rows}
    assert elements and all(e["evidence_id"] in ok_ids for e in elements)
    assert run["summary"]["extractor_mix"] == {"fallback": 4}


def test_unreachable_runner_means_the_fallback_only(
    app_factory: Callable[[Settings], FastAPI], dsettings: Settings, org: Org, owner_engine: Engine
) -> None:
    settings = dsettings.model_copy(
        update={"rea_enabled": True, "rea_local_command": ["node", "does-not-exist.mjs"]}
    )
    admin = client_for(app_factory(settings), org.users["admin"])
    system_id = create_system(admin)
    upload_estate_system(admin, system_id, "crm")
    run = run_discovery(admin, system_id)
    rows = evidence_rows(owner_engine, run["id"])
    assert (
        run["state"] == "DISCOVERING"
        and {r["extractor"] for r in rows} == {"fallback"}
        and len(rows) == 4
    )


def test_system_without_supported_evidence_fails_cleanly(
    app_factory: Callable[[Settings], FastAPI], fallback_settings: Settings, org: Org
) -> None:
    admin = client_for(app_factory(fallback_settings), org.users["admin"])
    system_id = create_system(admin)
    run = run_discovery(admin, system_id)
    assert run["state"] == "FAILED" and "no evidence" in run["error"]
    assert get_json(admin, f"/api/v1/systems/{system_id}")["status"] == "FAILED"


def test_a_corrupt_item_does_not_stop_the_run(
    app_factory: Callable[[Settings], FastAPI],
    fallback_settings: Settings,
    org: Org,
    owner_engine: Engine,
) -> None:
    admin = client_for(app_factory(fallback_settings), org.users["admin"])
    system_id = create_system(admin)
    ids = upload_estate_system(admin, system_id, "crm")
    with owner_engine.connect() as conn:
        path = conn.execute(
            text("SELECT storage_path FROM evidence_items WHERE id = :i"), {"i": ids[0]}
        ).scalar_one()
    stored = Path(fallback_settings.upload_dir) / path
    stored.write_bytes(stored.read_bytes()[:-3] + b"xyz")  # tamper with the encrypted HAR
    run = run_discovery(admin, system_id)
    assert run["state"] == "DISCOVERING"
    rows = evidence_rows(owner_engine, run["id"])
    assert (
        sum(r["status"] == "error" for r in rows) == 1
        and sum(r["status"] == "ok" for r in rows) == 3
    )
    assert any("authentication failed" in (r["error"] or "") for r in rows)


def test_registered_url_cannot_be_read_without_the_browser_runner(
    app_factory: Callable[[Settings], FastAPI],
    fallback_settings: Settings,
    org: Org,
    owner_engine: Engine,
) -> None:
    admin = client_for(app_factory(fallback_settings), org.users["admin"])
    system_id = create_system(admin)
    response = admin.post(
        f"/api/v1/systems/{system_id}/evidence/url",
        json={"url": "https://93.184.216.34/"},
        headers=csrf(admin),
    )
    assert response.status_code == 201
    run = run_discovery(admin, system_id)
    assert run["state"] == "FAILED"
    rows = evidence_rows(owner_engine, run["id"])
    assert len(rows) == 1 and rows[0]["status"] == "error" and "runner" in rows[0]["error"]


# --- permissions and isolation -----------------------------------------------------------------
def test_discovery_permissions_and_owner_scoping(
    app_factory: Callable[[Settings], FastAPI],
    fallback_settings: Settings,
    org: Org,
    other_org: Org,
) -> None:
    app = app_factory(fallback_settings)
    admin = client_for(app, org.users["admin"])
    owned = create_system(admin, "Owned", owner=org.users["system_owner"].id)
    other = create_system(admin, "Other")
    upload_estate_system(admin, owned, "newsletter")
    run_discovery(admin, owned)

    owner = client_for(app, org.users["system_owner"])
    viewer = client_for(app, org.users["viewer"])
    analyst = client_for(app, org.users["analyst"])
    outsider = client_for(app, other_org.users["admin"])

    assert (
        owner.post(f"/api/v1/systems/{owned}/discovery-runs", headers=csrf(owner)).status_code
        == 403
    )
    assert (
        viewer.post(f"/api/v1/systems/{owned}/discovery-runs", headers=csrf(viewer)).status_code
        == 403
    )
    assert (
        analyst.post(f"/api/v1/systems/{owned}/discovery-runs", headers=csrf(analyst)).status_code
        == 201
    )

    for path in ("data-elements", "recipients", "technologies", "discovery-runs"):
        assert owner.get(f"/api/v1/systems/{owned}/{path}").status_code == 200
        assert viewer.get(f"/api/v1/systems/{owned}/{path}").status_code == 200
        assert owner.get(f"/api/v1/systems/{other}/{path}").status_code == 404  # not their system
        assert (
            outsider.get(f"/api/v1/systems/{owned}/{path}").status_code == 404
        )  # another organization
    assert (
        outsider.post(f"/api/v1/systems/{owned}/discovery-runs", headers=csrf(outsider)).status_code
        == 404
    )

    evidence_id = get_json(admin, f"/api/v1/systems/{owned}/data-elements")[0]["evidence_id"]
    assert admin.get(f"/api/v1/discovery-evidence/{evidence_id}").status_code == 200
    assert viewer.get(f"/api/v1/discovery-evidence/{evidence_id}").status_code == 403
    assert owner.get(f"/api/v1/discovery-evidence/{evidence_id}").status_code == 403
    assert outsider.get(f"/api/v1/discovery-evidence/{evidence_id}").status_code == 404


def test_discovery_is_audited(
    app_factory: Callable[[Settings], FastAPI], fallback_settings: Settings, org: Org
) -> None:
    admin = client_for(app_factory(fallback_settings), org.users["admin"])
    system_id = create_system(admin)
    upload_estate_system(admin, system_id, "newsletter")
    run = run_discovery(admin, system_id)
    evidence_id = get_json(admin, f"/api/v1/systems/{system_id}/data-elements")[0]["evidence_id"]
    admin.get(f"/api/v1/discovery-evidence/{evidence_id}")
    entries = get_json(admin, "/api/v1/audit-log?limit=500")
    runs = [e for e in entries if e["action"] == "discovery.run"]
    assert (
        runs
        and runs[0]["details"]["run_id"] == run["id"]
        and runs[0]["details"]["extractor_mix"] == {"fallback": 4}
    )
    assert any(e["action"] == "discovery.evidence_view" for e in entries)


def test_plaintext_staging_is_cleaned_up(
    app_factory: Callable[[Settings], FastAPI], fallback_settings: Settings, org: Org
) -> None:
    admin = client_for(app_factory(fallback_settings), org.users["admin"])
    system_id = create_system(admin)
    upload_estate_system(admin, system_id, "hr_onboarding")
    run_discovery(admin, system_id)
    staging = Path(fallback_settings.rea_input_dir)
    assert not staging.exists() or not any(staging.iterdir())
