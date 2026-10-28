"""Log review as a test: everything the platform logs during sign in, a failed sign in, an access
request, a search and an unhandled error contains no personal data, password, token or key."""

import json
import logging
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.fixtures_api import ENCRYPTION_KEY, JWT_SECRET, PASSWORD, csrf
from tests.fixtures_fusion import FusionEstate
from tests.test_dsar_acceptance import CASES, email_of, prepared

JWT = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")


def secrets_of(client: TestClient) -> set[str]:
    return {v for v in client.cookies.values() if len(v) >= 16}


def test_nothing_sensitive_is_logged_during_the_main_flows(
    fusion_estate: FusionEstate, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    admin = fusion_estate.admin
    identifier = email_of("RC03")
    local_part = identifier.split("@")[0]

    bad = TestClient(fusion_estate.app, base_url="https://testserver")
    bad.post(
        "/api/v1/auth/login",
        json={"email": "someone.else@example.test", "password": "Wrong-Password-1"},
    )
    prepared(admin, identifier)
    admin.get("/api/v1/access-requests", params={"limit": 50})
    admin.get("/api/v1/audit-log", params={"limit": 50})

    logged = caplog.text + "\n".join(r.getMessage() for r in caplog.records)
    for forbidden in (
        identifier,
        local_part,
        "someone.else@example.test",
        PASSWORD,
        "Wrong-Password-1",
        JWT_SECRET,
        ENCRYPTION_KEY,
        *secrets_of(admin),
    ):
        assert forbidden not in logged, forbidden
    assert not JWT.search(logged)
    assert admin.cookies.get("pl_csrf") not in logged


def test_the_log_of_an_unhandled_error_names_the_request_and_the_exception_type_only(
    app: FastAPI, caplog: pytest.LogCaptureFixture
) -> None:
    @app.get("/boom-for-the-log-test")
    def boom() -> None:
        raise ValueError(
            "alice@example.test sent token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0 and password hunter2"
        )

    caplog.set_level(logging.DEBUG)
    client = TestClient(app, base_url="https://testserver", raise_server_exceptions=False)
    response = client.get("/boom-for-the-log-test", headers={"X-Request-ID": "req-hygiene-0001"})
    assert response.status_code == 500
    body = json.dumps(response.json())
    for text in (caplog.text, body):
        assert "alice@example.test" not in text and "hunter2" not in text and not JWT.search(text)
    assert "ValueError" in caplog.text and "req-hygiene-0001" in caplog.text
    assert "Internal server error" in body


def test_the_dataset_has_cases_to_search_for() -> None:
    assert len(CASES) == 10 and csrf  # the flows above use the reference estate's request cases
