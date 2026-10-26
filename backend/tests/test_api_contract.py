"""The API contract: one error format, request ids, paging, and an OpenAPI document whose examples
are accepted by the API they document."""

import re
import typing
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.api.errors import REQUEST_ID_HEADER
from tests.fixtures_api import client_for, csrf
from tests.fixtures_fusion import FusionEstate


def flat_routes(app: FastAPI) -> list[APIRoute]:
    flat: list[Any] = []
    for top in app.routes:
        flat.extend(
            getattr(top, "original_router", top).routes
            if hasattr(top, "original_router")
            else [top]
        )
    return [r for r in flat if isinstance(r, APIRoute)]


def body_model(route: APIRoute) -> type[BaseModel] | None:
    if route.body_field is None:
        return None
    annotation = route.body_field.field_info.annotation
    for candidate in [annotation, *typing.get_args(annotation)]:
        if isinstance(candidate, type) and issubclass(candidate, BaseModel):
            return candidate
    return None


# -- errors and request ids ----------------------------------------------------------------------


def assert_envelope(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"detail", "error"}
    error = body["error"]
    assert error["code"] == code and error["status"] == status and error["message"]
    assert error["request_id"] and error["request_id"] == response.headers[REQUEST_ID_HEADER]
    return dict(body)


def test_every_kind_of_error_has_the_same_shape(fusion_estate: FusionEstate) -> None:
    fe = fusion_estate
    anonymous = TestClient(fe.app, base_url="https://testserver")
    admin, viewer = fe.admin, client_for(fe.app, fe.users["viewer"])
    assert_envelope(anonymous.get("/api/v1/systems"), 401, "unauthorized")
    assert_envelope(
        viewer.post("/api/v1/tasks", json={"title": "Not allowed"}, headers=csrf(viewer)),
        403,
        "forbidden",
    )
    assert_envelope(admin.get(f"/api/v1/systems/{uuid.uuid4()}"), 404, "not_found")
    assert_envelope(admin.get("/api/v1/no/such/route"), 404, "not_found")
    assert_envelope(admin.put("/api/v1/systems", headers=csrf(admin)), 405, "method_not_allowed")
    created = admin.post(
        "/api/v1/systems", json={"name": "Contract empty"}, headers=csrf(admin)
    ).json()
    assert_envelope(
        admin.post(f"/api/v1/systems/{created['id']}/onboard", headers=csrf(admin)), 409, "conflict"
    )
    assert_envelope(
        admin.post("/api/v1/tasks", json={"title": "x"}, headers=csrf(admin)),
        422,
        "validation_error",
    )
    assert_envelope(
        admin.post("/api/v1/tasks", json={"title": "Valid title"}), 403, "forbidden"
    )  # no CSRF header


def test_validation_errors_name_the_field_and_never_echo_the_value(
    fusion_estate: FusionEstate,
) -> None:
    admin = fusion_estate.admin
    secret = "super-secret-value-123"
    body = assert_envelope(
        admin.post("/api/v1/chat", json={"question": secret * 30}, headers=csrf(admin)),
        422,
        "validation_error",
    )
    assert secret not in str(body)
    assert isinstance(body["detail"], list) and body["detail"][0]["loc"] == ["body", "question"]
    assert body["error"]["message"].startswith("question:")
    assert set(body["detail"][0]) == {"type", "loc", "msg"}
    query = assert_envelope(
        admin.get("/api/v1/tasks", params={"limit": "many"}), 422, "validation_error"
    )
    assert query["detail"][0]["loc"] == ["query", "limit"]


def test_http_errors_keep_their_detail_for_existing_clients(fusion_estate: FusionEstate) -> None:
    body = assert_envelope(
        fusion_estate.admin.get(f"/api/v1/jobs/{uuid.uuid4()}"), 404, "not_found"
    )
    assert body["detail"] == "Job not found" and body["error"]["message"] == "Job not found"
    conflict = fusion_estate.admin.post(
        f"/api/v1/activities/{uuid.uuid4()}/dpia", json={}, headers=csrf(fusion_estate.admin)
    )
    assert conflict.status_code == 404 and conflict.json()["error"]["code"] == "not_found"


def test_structured_details_become_a_message(
    fusion_estate: FusionEstate, estate_records: dict[str, Any]
) -> None:
    admin = fusion_estate.admin
    response = admin.post(
        f"/api/v1/activities/{estate_records['clinic_portal']['id']}/submit", headers=csrf(admin)
    )
    body = assert_envelope(response, 409, "conflict")
    assert body["detail"]["missing_fields"] == ["special_category_condition"]
    assert body["error"]["message"] == "The record is incomplete"


def test_request_ids_are_generated_echoed_and_cleaned(fusion_estate: FusionEstate) -> None:
    client = TestClient(fusion_estate.app, base_url="https://testserver")
    generated = client.get("/health")
    assert re.fullmatch(r"[0-9a-f]{32}", generated.headers[REQUEST_ID_HEADER])
    assert client.get("/health").headers[REQUEST_ID_HEADER] != generated.headers[REQUEST_ID_HEADER]
    echoed = client.get("/health", headers={REQUEST_ID_HEADER: "trace-2026.10.23_abc"})
    assert echoed.headers[REQUEST_ID_HEADER] == "trace-2026.10.23_abc"
    for bad in ("short", "has spaces in it ok", "x" * 100, "bad\x7fchars12"):
        replaced = client.get("/health", headers={REQUEST_ID_HEADER: bad})
        assert replaced.headers[REQUEST_ID_HEADER] != bad and re.fullmatch(
            r"[0-9a-f]{32}", replaced.headers[REQUEST_ID_HEADER]
        )
    error = client.get("/api/v1/systems", headers={REQUEST_ID_HEADER: "client-supplied-id-1"})
    assert error.json()["error"]["request_id"] == "client-supplied-id-1"


def test_an_unexpected_failure_returns_the_id_and_nothing_else(
    fusion_estate: FusionEstate, caplog: pytest.LogCaptureFixture
) -> None:
    from app.main import create_app

    app = create_app(
        fusion_estate.app.state.settings,
        fusion_estate.app.state.session_factory,
        embedder=fusion_estate.app.state.embedder,
        llm_router=fusion_estate.app.state.llm_router,
    )

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("the secret internal detail 4711")

    client = TestClient(app, base_url="https://testserver", raise_server_exceptions=False)
    response = client.get("/boom", headers={REQUEST_ID_HEADER: "boom-request-0001"})
    body = assert_envelope(response, 500, "internal_error")
    assert "4711" not in response.text and body["detail"] == "Internal server error"
    assert body["error"]["request_id"] == "boom-request-0001"
    assert any(
        "boom-request-0001" in r.getMessage() and "RuntimeError" in r.getMessage()
        for r in caplog.records
    )
    assert "4711" not in caplog.text  # the log carries the id and the type, not the message


def test_rate_limited_requests_use_the_same_format(
    fusion_estate: FusionEstate, session_factory: Any
) -> None:
    from app.main import create_app

    settings = fusion_estate.app.state.settings.model_copy(update={"login_rate_limit": "2/minute"})
    app = create_app(
        settings,
        session_factory,
        embedder=fusion_estate.app.state.embedder,
        llm_router=fusion_estate.app.state.llm_router,
    )
    client = TestClient(app, base_url="https://testserver")
    codes = [
        client.post(
            "/api/v1/auth/login", json={"email": "nobody@example.test", "password": "x" * 14}
        ).status_code
        for _ in range(4)
    ]
    assert codes[:2] == [401, 401] and codes[2:] == [429, 429]
    limited = client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.test", "password": "x" * 14}
    )
    assert_envelope(limited, 429, "rate_limited")
    assert limited.headers["retry-after"] == "60"


# -- paging --------------------------------------------------------------------------------------

PAGED = [
    "/api/v1/systems",
    "/api/v1/findings",
    "/api/v1/activities",
    "/api/v1/access-requests",
    "/api/v1/jobs",
    "/api/v1/tasks",
    "/api/v1/notifications",
    "/api/v1/vendors",
    "/api/v1/leads",
]


@pytest.mark.parametrize("path", PAGED)
def test_lists_report_their_total_and_honour_limit_and_offset(
    fusion_estate: FusionEstate, path: str
) -> None:
    admin = fusion_estate.admin
    everything = admin.get(path, params={"limit": 200})
    assert everything.status_code == 200
    total = int(everything.headers["x-total-count"])
    assert total >= len(everything.json()) and (total == len(everything.json()) or total > 200)
    if total >= 2:
        first = admin.get(path, params={"limit": 1})
        second = admin.get(path, params={"limit": 1, "offset": 1})
        assert len(first.json()) == len(second.json()) == 1 and first.json() != second.json()
        assert first.headers["x-total-count"] == str(total)
    assert admin.get(path, params={"offset": total + 5}).json() == []
    assert admin.get(path, params={"limit": 0}).status_code == 422
    assert admin.get(path, params={"limit": 100000}).status_code == 422
    assert admin.get(path, params={"offset": -1}).status_code == 422


# -- OpenAPI -------------------------------------------------------------------------------------


def test_the_documentation_is_served(fusion_estate: FusionEstate) -> None:
    client = TestClient(fusion_estate.app, base_url="https://testserver")
    assert client.get("/docs").status_code == 200 and "swagger" in client.get("/docs").text.lower()
    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    document = schema.json()
    assert document["info"]["title"] == "ProcessLedger API" and len(document["paths"]) >= 85
    operation_ids = [
        op["operationId"] for path in document["paths"].values() for op in path.values()
    ]
    assert len(operation_ids) == len(set(operation_ids))
    tags = {
        t for path in document["paths"].values() for op in path.values() for t in op.get("tags", [])
    }
    assert {
        "jobs",
        "workflow",
        "platform",
        "public",
        "access-requests",
        "impact-assessments",
        "records",
        "fusion",
        "llm",
    } <= tags


def test_every_route_is_documented(fusion_estate: FusionEstate) -> None:
    undocumented = []
    for route in flat_routes(fusion_estate.app):
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            if not route.tags and route.path not in ("/health", "/ready"):
                undocumented.append((method, route.path, "no tag"))
            if not (
                route.response_model or route.status_code == 204 or route.response_class is not None
            ):
                undocumented.append((method, route.path, "no response model"))
    # file downloads and the event stream declare their media type instead of a model
    allowed = {
        "/api/v1/exports/register.xlsx",
        "/api/v1/exports/register.pdf",
        "/api/v1/jobs/{job_id}/events",
        "/api/v1/dpias/{dpia_id}/export.pdf",
        "/health",
        "/ready",
    }
    assert [u for u in undocumented if u[1] not in allowed] == []


def test_every_json_request_body_has_examples_that_the_model_accepts(
    fusion_estate: FusionEstate,
) -> None:
    checked = 0
    for route in flat_routes(fusion_estate.app):
        model = body_model(route)
        if model is None or model.__name__.startswith("Body_"):
            continue  # file uploads are forms, not JSON
        examples = model.model_json_schema().get("examples")
        assert examples, f"{sorted(route.methods)} {route.path}: {model.__name__} has no example"
        for example in examples:
            model.model_validate(example)
            checked += 1
    assert checked >= 35


def test_the_documented_examples_are_accepted_by_the_running_api(
    fusion_estate: FusionEstate,
) -> None:
    """Send each example to its route: whatever the answer, it must not be a validation error."""
    admin = fusion_estate.admin
    anonymous = TestClient(fusion_estate.app, base_url="https://testserver")
    sent = 0
    for route in flat_routes(fusion_estate.app):
        model = body_model(route)
        if model is None or model.__name__.startswith("Body_"):
            continue
        path = re.sub(r"\{[^}]+\}", lambda _: str(uuid.uuid4()), route.path)
        client = (
            anonymous
            if route.path.startswith("/api/v1/public") or route.path.endswith("/auth/login")
            else admin
        )
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            for example in model.model_json_schema()["examples"]:
                headers = csrf(client) if client is admin else {}
                response = client.request(method, path, json=example, headers=headers)
                schema_error = response.status_code == 422 and isinstance(
                    response.json().get("detail"), list
                )
                assert not schema_error, (method, route.path, example, response.text)
                assert response.status_code != 500, (method, route.path)
                sent += 1
    assert sent >= 35


def test_examples_in_the_schema_match_their_models() -> None:
    from app.api import schemas

    for model, examples in schemas.EXAMPLES.items():
        assert model.model_json_schema()["examples"] == examples
        for example in examples:
            model.model_validate(example)
