import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.db.enums import Role
from tests.fixtures_api import Org, client_for, csrf, login

HAR = b'{"log": {"entries": []}}'
ALL = {Role.ADMIN, Role.ANALYST, Role.SYSTEM_OWNER, Role.VIEWER}

PUBLIC_ROUTES = {
    ("GET", "/health"),
    ("GET", "/ready"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/refresh"),
    ("POST", "/api/v1/auth/logout"),
}


def _dependency_calls(dependant: Any) -> list[Any]:
    calls = []
    for dep in dependant.dependencies:
        calls.append(dep.call)
        calls.extend(_dependency_calls(dep))
    return calls


def _protected_routes(app: FastAPI) -> list[tuple[str, APIRoute]]:
    found = []
    flat: list[Any] = []
    for top in app.routes:
        # Newer FastAPI wraps included routers; their route paths already carry the prefix.
        flat.extend(
            getattr(top, "original_router", top).routes
            if hasattr(top, "original_router")
            else [top]
        )
    for route in flat:
        if isinstance(route, APIRoute):
            for method in sorted(route.methods):
                if (method, route.path) not in PUBLIC_ROUTES:
                    found.append((method, route))
    return found


def test_every_route_declares_its_roles(app: FastAPI) -> None:
    protected = _protected_routes(app)
    assert len(protected) == 60
    for method, route in protected:
        roles = [
            getattr(call, "allowed_roles", None)
            for call in _dependency_calls(route.dependant)
            if hasattr(call, "allowed_roles")
        ]
        assert roles, f"{method} {route.path} has no require_role dependency"
        assert roles[0] <= ALL


def test_every_protected_route_rejects_anonymous_requests(client: TestClient, app: FastAPI) -> None:
    for method, route in _protected_routes(app):
        path = route.path.replace("{system_id}", str(uuid.uuid4()))
        response = client.request(method, path)
        assert response.status_code == 401, f"{method} {route.path} -> {response.status_code}"


# --- role matrix -----------------------------------------------------------------------------


def _upload(c: TestClient, system_id: str) -> Any:
    return c.post(
        f"/api/v1/systems/{system_id}/evidence",
        data={"kind": "har"},
        files={"file": ("cap.har", HAR, "application/json")},
        headers=csrf(c),
    )


@pytest.fixture
def matrix_setup(app: FastAPI, org: Org) -> dict[str, Any]:
    admin = client_for(app, org.users["admin"])
    owned = admin.post(
        "/api/v1/systems",
        json={"name": "Shop", "owner_user_id": str(org.users["system_owner"].id)},
        headers=csrf(admin),
    ).json()
    clients = {role: client_for(app, org.users[role.value]) for role in Role}
    return {"system_id": owned["id"], "clients": clients, "admin": admin}


def _matrix(
    sys_id: str,
) -> list[tuple[str, str, Callable[[TestClient], Any], set[Role]]]:
    def create(c: TestClient) -> Any:
        return c.post(
            "/api/v1/systems",
            json={"name": f"N{uuid.uuid4().hex[:6]}"},
            headers=csrf(c),
        )

    def delete(c: TestClient) -> Any:
        return c.delete(f"/api/v1/systems/{uuid.uuid4()}", headers=csrf(c))

    return [
        ("GET", "/systems", lambda c: c.get("/api/v1/systems"), ALL),
        ("POST", "/systems", create, {Role.ADMIN, Role.ANALYST}),
        ("GET", "/systems/{id}", lambda c: c.get(f"/api/v1/systems/{sys_id}"), ALL),
        (
            "PATCH",
            "/systems/{id}",
            lambda c: c.patch(
                f"/api/v1/systems/{sys_id}", json={"description": "x"}, headers=csrf(c)
            ),
            {Role.ADMIN, Role.ANALYST},
        ),
        ("DELETE", "/systems/{id}", delete, {Role.ADMIN}),
        (
            "GET",
            "/evidence",
            lambda c: c.get(f"/api/v1/systems/{sys_id}/evidence"),
            ALL,
        ),
        (
            "POST",
            "/evidence",
            lambda c: _upload(c, sys_id),
            {Role.ADMIN, Role.ANALYST, Role.SYSTEM_OWNER},
        ),
        (
            "POST",
            "/evidence/url",
            lambda c: c.post(
                f"/api/v1/systems/{sys_id}/evidence/url",
                json={"url": "https://93.184.216.34/"},
                headers=csrf(c),
            ),
            {Role.ADMIN, Role.ANALYST},
        ),
        ("GET", "/settings", lambda c: c.get("/api/v1/settings"), {Role.ADMIN}),
        (
            "PUT",
            "/settings",
            lambda c: c.put("/api/v1/settings", json={}, headers=csrf(c)),
            {Role.ADMIN},
        ),
        (
            "GET",
            "/audit-log",
            lambda c: c.get("/api/v1/audit-log"),
            {Role.ADMIN, Role.VIEWER},
        ),
        ("GET", "/auth/me", lambda c: c.get("/api/v1/auth/me"), ALL),
        (
            "POST",
            "/discovery-runs",
            lambda c: c.post(f"/api/v1/systems/{sys_id}/discovery-runs", headers=csrf(c)),
            {Role.ADMIN, Role.ANALYST},
        ),
        (
            "GET",
            "/discovery-runs",
            lambda c: c.get(f"/api/v1/systems/{sys_id}/discovery-runs"),
            ALL,
        ),
        ("GET", "/data-elements", lambda c: c.get(f"/api/v1/systems/{sys_id}/data-elements"), ALL),
        ("GET", "/recipients", lambda c: c.get(f"/api/v1/systems/{sys_id}/recipients"), ALL),
        ("GET", "/technologies", lambda c: c.get(f"/api/v1/systems/{sys_id}/technologies"), ALL),
        ("GET", "/taxonomy", lambda c: c.get("/api/v1/taxonomy"), ALL),
        (
            "POST",
            "/classification",
            lambda c: c.post(f"/api/v1/systems/{sys_id}/classification", headers=csrf(c)),
            {Role.ADMIN, Role.ANALYST},
        ),
        (
            "PATCH",
            "/data-elements/{id}",
            lambda c: c.patch(
                f"/api/v1/systems/{sys_id}/data-elements/{uuid.uuid4()}",
                json={"review_status": "accepted"},
                headers=csrf(c),
            ),
            {Role.ADMIN, Role.ANALYST},
        ),
        (
            "POST",
            "/knowledge/search",
            lambda c: c.post(
                "/api/v1/knowledge/search", json={"query": "breach notification"}, headers=csrf(c)
            ),
            ALL,
        ),
        (
            "GET",
            "/knowledge/passage",
            lambda c: c.get("/api/v1/knowledge/passage", params={"citation": "reg:gdpr-art30-p1"}),
            ALL,
        ),
        ("GET", "/knowledge/documents", lambda c: c.get("/api/v1/knowledge/documents"), ALL),
        (
            "POST",
            "/knowledge/documents",
            lambda c: c.post(
                "/api/v1/knowledge/documents",
                data={"doc_type": "policy"},
                files={"file": ("p.md", b"## A\n\nSome policy text here.", "text/markdown")},
                headers=csrf(c),
            ),
            {Role.ADMIN, Role.ANALYST},
        ),
        (
            "DELETE",
            "/knowledge/documents/{id}",
            lambda c: c.delete(f"/api/v1/knowledge/documents/{uuid.uuid4()}", headers=csrf(c)),
            {Role.ADMIN, Role.ANALYST},
        ),
        (
            "POST",
            "/knowledge/ingest",
            lambda c: c.post(f"/api/v1/systems/{sys_id}/knowledge/ingest", headers=csrf(c)),
            {Role.ADMIN, Role.ANALYST, Role.SYSTEM_OWNER},
        ),
        (
            "GET",
            "/llm/usage",
            lambda c: c.get("/api/v1/llm/usage"),
            {Role.ADMIN, Role.ANALYST, Role.VIEWER},
        ),
        (
            "POST",
            "/llm/test-connection",
            lambda c: c.post("/api/v1/llm/test-connection", headers=csrf(c)),
            {Role.ADMIN},
        ),
        (
            "POST",
            "/fusion",
            lambda c: c.post(f"/api/v1/systems/{sys_id}/fusion", headers=csrf(c)),
            {Role.ADMIN, Role.ANALYST},
        ),
        ("GET", "/findings", lambda c: c.get("/api/v1/findings"), ALL),
        (
            "PATCH",
            "/findings/{id}",
            lambda c: c.patch(
                f"/api/v1/findings/{uuid.uuid4()}", json={"status": "dismissed"}, headers=csrf(c)
            ),
            {Role.ADMIN, Role.ANALYST},
        ),
        (
            "POST",
            "/record",
            lambda c: c.post(f"/api/v1/systems/{sys_id}/record", headers=csrf(c)),
            {Role.ADMIN, Role.ANALYST},
        ),
        ("GET", "/activities", lambda c: c.get("/api/v1/activities"), ALL),
        ("GET", "/activities/{id}", lambda c: c.get(f"/api/v1/activities/{uuid.uuid4()}"), ALL),
        (
            "GET",
            "/activities/{id}/versions",
            lambda c: c.get(f"/api/v1/activities/{uuid.uuid4()}/versions"),
            ALL,
        ),
        (
            "GET",
            "/activities/{id}/versions/{n}",
            lambda c: c.get(f"/api/v1/activities/{uuid.uuid4()}/versions/1"),
            ALL,
        ),
        (
            "GET",
            "/activities/{id}/diff",
            lambda c: c.get(f"/api/v1/activities/{uuid.uuid4()}/diff", params={"from": 1, "to": 2}),
            ALL,
        ),
        (
            "PATCH",
            "/activities/{id}",
            lambda c: c.patch(
                f"/api/v1/activities/{uuid.uuid4()}", json={"retention": "1 year"}, headers=csrf(c)
            ),
            {Role.ADMIN, Role.ANALYST},
        ),
        (
            "POST",
            "/activities/{id}/submit",
            lambda c: c.post(f"/api/v1/activities/{uuid.uuid4()}/submit", headers=csrf(c)),
            {Role.ADMIN, Role.ANALYST},
        ),
        (
            "POST",
            "/activities/{id}/approve",
            lambda c: c.post(
                f"/api/v1/activities/{uuid.uuid4()}/approve", json={}, headers=csrf(c)
            ),
            {Role.ADMIN},
        ),
        (
            "POST",
            "/activities/{id}/reject",
            lambda c: c.post(f"/api/v1/activities/{uuid.uuid4()}/reject", json={}, headers=csrf(c)),
            {Role.ADMIN},
        ),
        (
            "POST",
            "/activities/{id}/publish",
            lambda c: c.post(f"/api/v1/activities/{uuid.uuid4()}/publish", headers=csrf(c)),
            {Role.ADMIN},
        ),
        (
            "GET",
            "/review-queue",
            lambda c: c.get("/api/v1/review-queue"),
            {Role.ADMIN, Role.ANALYST},
        ),
        (
            "GET",
            "/exports/register.xlsx",
            lambda c: c.get("/api/v1/exports/register.xlsx"),
            {Role.ADMIN, Role.ANALYST, Role.VIEWER},
        ),
        (
            "GET",
            "/exports/register.pdf",
            lambda c: c.get("/api/v1/exports/register.pdf"),
            {Role.ADMIN, Role.ANALYST, Role.VIEWER},
        ),
        (
            "POST",
            "/dpia-screening",
            lambda c: c.post(f"/api/v1/activities/{uuid.uuid4()}/dpia-screening", headers=csrf(c)),
            {Role.ADMIN, Role.ANALYST},
        ),
        (
            "GET",
            "/dpia-screening",
            lambda c: c.get(f"/api/v1/activities/{uuid.uuid4()}/dpia-screening"),
            ALL,
        ),
        ("GET", "/dpia-screenings", lambda c: c.get("/api/v1/dpia-screenings"), ALL),
        (
            "POST",
            "/dpia",
            lambda c: c.post(f"/api/v1/activities/{uuid.uuid4()}/dpia", json={}, headers=csrf(c)),
            {Role.ADMIN, Role.ANALYST},
        ),
        ("GET", "/dpias", lambda c: c.get("/api/v1/dpias"), ALL),
        ("GET", "/dpias/{id}", lambda c: c.get(f"/api/v1/dpias/{uuid.uuid4()}"), ALL),
        (
            "PATCH",
            "/dpias/{id}",
            lambda c: c.patch(
                f"/api/v1/dpias/{uuid.uuid4()}", json={"description": "x"}, headers=csrf(c)
            ),
            {Role.ADMIN, Role.ANALYST},
        ),
        (
            "POST",
            "/dpias/{id}/risks",
            lambda c: c.post(
                f"/api/v1/dpias/{uuid.uuid4()}/risks",
                json={"title": "A risk", "likelihood": 2, "severity": 2},
                headers=csrf(c),
            ),
            {Role.ADMIN, Role.ANALYST},
        ),
        (
            "PATCH",
            "/dpias/{id}/risks/{rid}",
            lambda c: c.patch(
                f"/api/v1/dpias/{uuid.uuid4()}/risks/{uuid.uuid4()}",
                json={"likelihood": 3},
                headers=csrf(c),
            ),
            {Role.ADMIN, Role.ANALYST},
        ),
        (
            "DELETE",
            "/dpias/{id}/risks/{rid}",
            lambda c: c.delete(
                f"/api/v1/dpias/{uuid.uuid4()}/risks/{uuid.uuid4()}", headers=csrf(c)
            ),
            {Role.ADMIN, Role.ANALYST},
        ),
        (
            "POST",
            "/dpias/{id}/submit",
            lambda c: c.post(f"/api/v1/dpias/{uuid.uuid4()}/submit", headers=csrf(c)),
            {Role.ADMIN, Role.ANALYST},
        ),
        (
            "POST",
            "/dpias/{id}/approve",
            lambda c: c.post(f"/api/v1/dpias/{uuid.uuid4()}/approve", json={}, headers=csrf(c)),
            {Role.ADMIN},
        ),
        (
            "POST",
            "/dpias/{id}/reject",
            lambda c: c.post(f"/api/v1/dpias/{uuid.uuid4()}/reject", json={}, headers=csrf(c)),
            {Role.ADMIN},
        ),
        (
            "GET",
            "/dpias/{id}/export.pdf",
            lambda c: c.get(f"/api/v1/dpias/{uuid.uuid4()}/export.pdf"),
            {Role.ADMIN, Role.ANALYST, Role.VIEWER},
        ),
        (
            "GET",
            "/discovery-evidence/{id}",
            lambda c: c.get(f"/api/v1/discovery-evidence/{uuid.uuid4()}"),
            {Role.ADMIN, Role.ANALYST},
        ),
    ]


def test_role_matrix(matrix_setup: dict[str, Any]) -> None:
    clients: dict[Role, TestClient] = matrix_setup["clients"]
    for method, path, call, allowed in _matrix(matrix_setup["system_id"]):
        for role, c in clients.items():
            status = call(c).status_code
            if role in allowed:
                assert status not in (
                    401,
                    403,
                ), f"{role} should reach {method} {path}: {status}"
            else:
                assert status == 403, f"{role} must be refused {method} {path}: {status}"


# --- system owner scoping --------------------------------------------------------------------


def test_system_owner_sees_and_touches_only_owned_systems(
    app: FastAPI, org: Org, matrix_setup: dict[str, Any]
) -> None:
    admin: TestClient = matrix_setup["admin"]
    other = admin.post("/api/v1/systems", json={"name": "Unowned"}, headers=csrf(admin)).json()
    owner = matrix_setup["clients"][Role.SYSTEM_OWNER]

    listed = owner.get("/api/v1/systems").json()
    assert [s["id"] for s in listed] == [matrix_setup["system_id"]]
    assert owner.get(f"/api/v1/systems/{matrix_setup['system_id']}").status_code == 200

    # Systems they do not own do not exist as far as they are concerned.
    assert owner.get(f"/api/v1/systems/{other['id']}").status_code == 404
    assert owner.get(f"/api/v1/systems/{other['id']}/evidence").status_code == 404
    assert _upload(owner, other["id"]).status_code == 404
    assert _upload(owner, matrix_setup["system_id"]).status_code == 201

    # Analysts and auditors see everything.
    for role in (Role.ANALYST, Role.VIEWER, Role.ADMIN):
        assert len(matrix_setup["clients"][role].get("/api/v1/systems").json()) == 2


def test_owner_must_belong_to_the_organization(
    app: FastAPI, org: Org, other_org: Org, matrix_setup: dict[str, Any]
) -> None:
    admin: TestClient = matrix_setup["admin"]
    response = admin.post(
        "/api/v1/systems",
        json={"name": "Bad owner", "owner_user_id": str(other_org.users["admin"].id)},
        headers=csrf(admin),
    )
    assert response.status_code == 422


# --- tenant isolation through the API ----------------------------------------------------------


def test_other_organization_cannot_see_or_change_systems(
    app: FastAPI, other_org: Org, matrix_setup: dict[str, Any]
) -> None:
    sys_id = matrix_setup["system_id"]
    outsider = client_for(app, other_org.users["admin"])
    assert outsider.get("/api/v1/systems").json() == []
    assert outsider.get(f"/api/v1/systems/{sys_id}").status_code == 404
    assert outsider.get(f"/api/v1/systems/{sys_id}/evidence").status_code == 404
    assert (
        outsider.patch(
            f"/api/v1/systems/{sys_id}", json={"name": "hijack"}, headers=csrf(outsider)
        ).status_code
        == 404
    )
    assert outsider.delete(f"/api/v1/systems/{sys_id}", headers=csrf(outsider)).status_code == 404
    assert _upload(outsider, sys_id).status_code == 404
    assert matrix_setup["admin"].get(f"/api/v1/systems/{sys_id}").json()["name"] == "Shop"
    # The audit log is per organization too.
    assert not any(e["entity_id"] == sys_id for e in outsider.get("/api/v1/audit-log").json())


def test_duplicate_system_name_conflicts(matrix_setup: dict[str, Any]) -> None:
    admin: TestClient = matrix_setup["admin"]
    assert (
        admin.post("/api/v1/systems", json={"name": "Shop"}, headers=csrf(admin)).status_code == 409
    )


# --- CSRF ---------------------------------------------------------------------------------------


def test_state_changing_requests_require_the_csrf_header(app: FastAPI, org: Org) -> None:
    c = client_for(app, org.users["admin"])
    body = {"name": "CSRF probe"}
    assert c.post("/api/v1/systems", json=body).status_code == 403
    assert (
        c.post("/api/v1/systems", json=body, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    )
    assert c.put("/api/v1/settings", json={}).status_code == 403
    assert c.delete(f"/api/v1/systems/{uuid.uuid4()}").status_code == 403
    assert c.post("/api/v1/auth/logout").status_code == 403
    assert c.post("/api/v1/systems", json=body, headers=csrf(c)).status_code == 201
    # Reads need no header.
    assert c.get("/api/v1/systems").status_code == 200


def test_csrf_header_from_another_session_is_rejected(app: FastAPI, org: Org) -> None:
    a = client_for(app, org.users["admin"])
    b = client_for(app, org.users["analyst"])
    response = a.post("/api/v1/systems", json={"name": "x"}, headers=csrf(b))
    assert response.status_code == 403


# --- rate limiting, headers, CORS ----------------------------------------------------------------


def test_login_is_rate_limited(make_app: Callable[..., FastAPI], settings: Any, org: Org) -> None:
    strict = settings.model_copy(update={"login_rate_limit": "3/minute"})
    with TestClient(make_app(strict), base_url="https://testserver") as c:
        codes = [
            login(c, org.users["admin"].email, "wrong-password-xyz").status_code for _ in range(5)
        ]
    assert codes == [401, 401, 401, 429, 429]


def test_default_rate_limit_applies_to_every_route(
    make_app: Callable[..., FastAPI], settings: Any
) -> None:
    strict = settings.model_copy(update={"default_rate_limit": "5/minute"})
    with TestClient(make_app(strict), base_url="https://testserver") as c:
        codes = [c.get("/health").status_code for _ in range(7)]
    assert codes[:5] == [200] * 5 and codes[5:] == [429, 429]


def test_security_headers_on_every_response(client: TestClient, org: Org) -> None:
    for response in (
        client.get("/health"),
        client.get("/api/v1/systems"),
        client.get("/nope"),
    ):
        h = response.headers
        assert "default-src 'none'" in h["content-security-policy"]
        assert "frame-ancestors 'none'" in h["content-security-policy"]
        assert "max-age=" in h["strict-transport-security"]
        assert h["x-content-type-options"] == "nosniff"
        assert h["referrer-policy"] == "no-referrer"
        assert h["x-frame-options"] == "DENY"
    assert client.get("/api/v1/systems").headers["cache-control"] == "no-store"


def test_cors_allows_only_listed_origins(client: TestClient) -> None:
    headers = {
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-csrf-token",
    }
    good = client.options(
        "/api/v1/systems", headers={**headers, "Origin": "https://app.example.test"}
    )
    assert good.headers["access-control-allow-origin"] == "https://app.example.test"
    assert good.headers["access-control-allow-credentials"] == "true"
    bad = client.options("/api/v1/systems", headers={**headers, "Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in bad.headers
    plain = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in plain.headers


def test_health_and_ready(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready"}


# --- audit coverage -------------------------------------------------------------------------------


def test_security_relevant_actions_are_audited(
    app: FastAPI, org: Org, matrix_setup: dict[str, Any], owner_engine: Engine
) -> None:
    admin: TestClient = matrix_setup["admin"]
    sys_id = matrix_setup["system_id"]
    assert _upload(admin, sys_id).status_code == 201
    admin.post(
        f"/api/v1/systems/{sys_id}/evidence/url",
        json={"url": "https://93.184.216.34/"},
        headers=csrf(admin),
    )
    admin.post(
        f"/api/v1/systems/{sys_id}/evidence/url",
        json={"url": "http://127.0.0.1/"},
        headers=csrf(admin),
    )
    admin.put("/api/v1/settings", json={"evidence_retention_days": 30}, headers=csrf(admin))
    admin.post("/api/v1/auth/logout", headers=csrf(admin))

    viewer = matrix_setup["clients"][Role.VIEWER]
    actions = {e["action"] for e in viewer.get("/api/v1/audit-log", params={"limit": 500}).json()}
    assert {
        "auth.login",
        "system.create",
        "evidence.upload",
        "evidence.url_registered",
        "evidence.url_rejected",
        "settings.update",
        "auth.logout",
    } <= actions

    entry = next(
        e for e in viewer.get("/api/v1/audit-log", params={"action": "evidence.upload"}).json()
    )
    assert entry["actor_user_id"] == str(org.users["admin"].id)
    assert entry["details"] == {"kind": "har", "size": len(HAR)}
    with owner_engine.connect() as conn:  # no personal data in audit details
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE org_id = :o AND details::text ILIKE '%@%'"
                ),
                {"o": org.id},
            ).scalar_one()
            == 0
        )
