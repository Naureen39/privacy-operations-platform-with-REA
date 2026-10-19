from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.core.config import Settings
from app.core.security import create_access_token
from app.db.enums import Role
from app.services import provisioning
from tests.fixtures_api import JWT_SECRET, PASSWORD, Org, client_for, csrf, login


def set_cookie_headers(response) -> list[str]:  # type: ignore[no-untyped-def]
    return response.headers.get_list("set-cookie")


def cookie_header(response, name: str) -> str:  # type: ignore[no-untyped-def]
    return next(h for h in set_cookie_headers(response) if h.startswith(f"{name}="))


def test_login_sets_hardened_cookies(client: TestClient, org: Org) -> None:
    response = login(client, org.users["analyst"].email)
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "analyst" and body["org_id"] == str(org.id)
    assert "password" not in response.text

    for name in ("pl_access", "pl_refresh"):
        header = cookie_header(response, name).lower()
        assert "httponly" in header and "secure" in header and "samesite=lax" in header
    assert "path=/api/v1/auth" in cookie_header(response, "pl_refresh").lower()
    csrf_header = cookie_header(response, "pl_csrf").lower()
    assert "httponly" not in csrf_header and "secure" in csrf_header
    assert "max-age=900" in cookie_header(response, "pl_access").lower()  # 15 minutes
    assert "max-age=604800" in cookie_header(response, "pl_refresh").lower()  # 7 days


def test_me_requires_a_session_and_returns_identity(client: TestClient, org: Org) -> None:
    assert client.get("/api/v1/auth/me").status_code == 401
    login(client, org.users["admin"].email)
    me = client.get("/api/v1/auth/me").json()
    assert me["role"] == "admin" and me["user"]["email"] == org.users["admin"].email


def test_registration_is_disabled(client: TestClient) -> None:
    for path in ("/api/v1/auth/register", "/api/v1/auth/signup", "/api/v1/users"):
        assert client.post(
            path, json={"email": "x@example.test", "password": PASSWORD}
        ).status_code in (
            404,
            405,
        )


def test_failures_look_identical_for_unknown_and_known_accounts(
    client: TestClient, org: Org
) -> None:
    unknown = login(client, "nobody@acme.example", PASSWORD)
    wrong = login(client, org.users["admin"].email, "wrong-password-xyz")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()
    assert not set_cookie_headers(unknown) and not set_cookie_headers(wrong)


def test_lockout_after_repeated_failures(
    client: TestClient, org: Org, owner_engine: Engine, settings: Settings
) -> None:
    email = org.users["viewer"].email
    for _ in range(settings.max_failed_logins):
        assert login(client, email, "wrong-password-xyz").status_code == 401
    # Locked: even the correct password is refused.
    assert login(client, email).status_code == 401
    with owner_engine.connect() as conn:
        locked_until = conn.execute(
            text("SELECT locked_until FROM users WHERE lower(email) = :e"),
            {"e": email.lower()},
        ).scalar_one()
    assert locked_until > datetime.now(UTC) + timedelta(minutes=10)

    # Once the lock expires the account works again and the counter is cleared.
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE users SET locked_until = now() - interval '1 minute' WHERE lower(email)=:e"
            ),
            {"e": email.lower()},
        )
    assert login(client, email).status_code == 200


def test_failed_attempts_below_the_limit_do_not_lock(client: TestClient, org: Org) -> None:
    email = org.users["viewer"].email
    for _ in range(3):
        login(client, email, "wrong-password-xyz")
    assert login(client, email).status_code == 200


def test_lockout_and_failures_are_audited(app: FastAPI, client: TestClient, org: Org) -> None:
    email = org.users["viewer"].email
    for _ in range(5):
        login(client, email, "wrong-password-xyz")
    login(client, org.users["viewer"].email)  # locked, still failing

    admin = client_for(app, org.users["admin"])
    entries = admin.get("/api/v1/audit-log", params={"action": "auth.login_failed"}).json()
    # Failed logins have no organization, so tenants cannot read them. The successful
    # admin login is the entry visible here.
    assert entries == []
    actions = {e["action"] for e in admin.get("/api/v1/audit-log").json()}
    assert "auth.login" in actions


def test_failed_logins_are_recorded_without_the_email(
    client: TestClient, org: Org, owner_engine: Engine
) -> None:
    login(client, "ghost-user@acme.example", "wrong-password-xyz")
    with owner_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT details::text FROM audit_log WHERE action = 'auth.login_failed'")
        ).all()
    assert rows
    assert not any("ghost-user" in r[0] for r in rows)


def test_refresh_rotates_and_old_token_is_rejected(app: FastAPI, org: Org) -> None:
    c = client_for(app, org.users["analyst"])
    first = c.cookies.get("pl_refresh", path="/api/v1/auth")
    response = c.post("/api/v1/auth/refresh", headers=csrf(c))
    assert response.status_code == 204
    second = c.cookies.get("pl_refresh", path="/api/v1/auth")
    assert first and second and first != second
    assert c.get("/api/v1/auth/me").status_code == 200

    # Replaying the rotated token is treated as theft: the whole family is revoked.
    replay = TestClient(app, base_url="https://testserver")
    replay.cookies.set("pl_refresh", first, path="/api/v1/auth")
    replay.cookies.set("pl_csrf", "t")
    assert replay.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": "t"}).status_code == 401
    assert c.post("/api/v1/auth/refresh", headers=csrf(c)).status_code == 401


def test_refresh_requires_a_valid_cookie(client: TestClient) -> None:
    assert client.post("/api/v1/auth/refresh").status_code == 401
    client.cookies.set("pl_refresh", "made-up-value", path="/api/v1/auth")
    client.cookies.set("pl_csrf", "t")
    assert client.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": "t"}).status_code == 401


def test_logout_revokes_the_refresh_token(app: FastAPI, org: Org) -> None:
    c = client_for(app, org.users["analyst"])
    refresh_token = c.cookies.get("pl_refresh", path="/api/v1/auth")
    assert c.post("/api/v1/auth/logout", headers=csrf(c)).status_code == 204
    assert c.get("/api/v1/auth/me").status_code == 401

    stale = TestClient(app, base_url="https://testserver")
    stale.cookies.set("pl_refresh", refresh_token, path="/api/v1/auth")
    stale.cookies.set("pl_csrf", "t")
    assert stale.post("/api/v1/auth/refresh", headers={"X-CSRF-Token": "t"}).status_code == 401


def test_expired_and_forged_access_tokens_are_rejected(
    client: TestClient, org: Org, settings: Settings
) -> None:
    user = org.users["admin"]
    expired = create_access_token(
        JWT_SECRET,
        user.id,
        org.id,
        Role.ADMIN,
        15,
        now=datetime.now(UTC) - timedelta(hours=1),
    )
    client.cookies.set("pl_access", expired)
    assert client.get("/api/v1/auth/me").status_code == 401

    forged = create_access_token("f" * 40, user.id, org.id, Role.ADMIN, 15)
    client.cookies.set("pl_access", forged)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_token_claiming_a_role_cannot_exceed_the_database_role(
    client: TestClient, org: Org
) -> None:
    viewer = org.users["viewer"]
    token = create_access_token(JWT_SECRET, viewer.id, org.id, Role.ADMIN, 15)
    client.cookies.set("pl_access", token)
    assert client.get("/api/v1/auth/me").json()["role"] == "viewer"
    assert client.get("/api/v1/settings").status_code == 403


def test_deactivated_user_loses_access_immediately(
    app: FastAPI, org: Org, owner_engine: Engine
) -> None:
    c = client_for(app, org.users["analyst"])
    assert c.get("/api/v1/auth/me").status_code == 200
    with owner_engine.begin() as conn:
        conn.execute(
            text("UPDATE users SET is_active = false WHERE id = :i"),
            {"i": org.users["analyst"].id},
        )
    assert c.get("/api/v1/auth/me").status_code == 401
    assert c.post("/api/v1/auth/refresh", headers=csrf(c)).status_code == 401
    assert (
        login(
            TestClient(app, base_url="https://testserver"), org.users["analyst"].email
        ).status_code
        == 401
    )


def test_removed_membership_loses_access_immediately(
    app: FastAPI, org: Org, owner_engine: Engine
) -> None:
    c = client_for(app, org.users["analyst"])
    with owner_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM memberships WHERE user_id = :u"),
            {"u": org.users["analyst"].id},
        )
    assert c.get("/api/v1/auth/me").status_code == 401


def test_user_in_two_organizations_chooses_one(
    app: FastAPI, org: Org, other_org: Org, owner_engine: Engine
) -> None:
    shared = provisioning.create_user(
        owner_engine, org.id, "shared@acme.example", "Shared", PASSWORD, Role.ANALYST
    )
    provisioning.create_user(
        owner_engine,
        other_org.id,
        "shared@acme.example",
        "Shared",
        PASSWORD,
        Role.VIEWER,
    )
    c = TestClient(app, base_url="https://testserver")
    body = login(c, shared.email, org_id=other_org.id).json()
    assert body["org_id"] == str(other_org.id) and body["role"] == "viewer"
    assert {m["org_id"] for m in body["memberships"]} == {
        str(org.id),
        str(other_org.id),
    }

    outsider = TestClient(app, base_url="https://testserver")
    third = provisioning.create_organization(owner_engine, "Third", "third-" + str(org.id)[:8])
    assert login(outsider, shared.email, org_id=third).status_code == 403


def test_password_length_is_enforced_when_provisioning(owner_engine: Engine, org: Org) -> None:
    import pytest

    from app.core.security import WeakPasswordError

    with pytest.raises(WeakPasswordError):
        provisioning.create_user(
            owner_engine, org.id, "weak@acme.example", "Weak", "short", Role.VIEWER
        )
